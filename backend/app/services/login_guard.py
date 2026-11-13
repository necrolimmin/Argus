"""What stands in front of the sign-in: a picture of digits to type, and a
pause for whoever keeps getting the password wrong.

Everything is kept in memory: the backend is one process, a captcha lives a
few minutes, and a restart forgiving the counters is acceptable.
"""

import secrets
import time
from dataclasses import dataclass

from app.config import get_settings

CAPTCHA_SECONDS = 180
CAPTCHA_DIGITS = 5
# More pictures than this waiting for an answer means somebody is asking for
# them in a loop; the oldest are dropped.
CAPTCHA_KEEP = 5000

_rand = secrets.SystemRandom()
# id -> (answer, expires at)
_captchas: dict[str, tuple[str, float]] = {}


@dataclass
class _Tries:
    failures: int = 0
    last: float = 0.0
    locked_until: float = 0.0


_tries: dict[str, _Tries] = {}

# Seven-segment digits: each segment is a line between two corners of a
# 16x32 cell. Drawn as lines, not text, so the answer is not in the markup.
_CORNERS = {"tl": (0, 0), "tr": (16, 0), "ml": (0, 16), "mr": (16, 16), "bl": (0, 32), "br": (16, 32)}
_SEGMENTS = {
    "a": ("tl", "tr"),
    "b": ("tr", "mr"),
    "c": ("mr", "br"),
    "d": ("bl", "br"),
    "e": ("ml", "bl"),
    "f": ("tl", "ml"),
    "g": ("ml", "mr"),
}
_DIGITS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abfgcd",
}
_INKS = ("#12303a", "#1d3f6e", "#3a2a78", "#0d5a55")


def _jitter(amount: float) -> float:
    return _rand.uniform(-amount, amount)


def _picture(answer: str) -> str:
    width, height = 190, 64
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
    ]
    # Lines across the picture, in the digits' own colours and thickness.
    for _ in range(4):
        x1, y1 = _rand.uniform(0, width * 0.4), _rand.uniform(6, height - 6)
        x2, y2 = _rand.uniform(width * 0.6, width), _rand.uniform(6, height - 6)
        cx, cy = _rand.uniform(40, width - 40), _rand.uniform(-10, height + 10)
        parts.append(
            f'<path d="M{x1:.1f} {y1:.1f} Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" fill="none" '
            f'stroke="{_rand.choice(_INKS)}" stroke-width="{_rand.uniform(1.0, 2.0):.1f}" opacity="0.45"/>'
        )
    step = (width - 30) / len(answer)
    for i, ch in enumerate(answer):
        x = 18 + i * step + _jitter(3)
        y = 11 + _jitter(3)
        scale = _rand.uniform(1.18, 1.3)
        lines = []
        for seg in _DIGITS[ch]:
            a, b = _SEGMENTS[seg]
            (ax, ay), (bx, by) = _CORNERS[a], _CORNERS[b]
            lines.append(
                f"M{ax + _jitter(1.2):.1f} {ay + _jitter(1.2):.1f} L{bx + _jitter(1.2):.1f} {by + _jitter(1.2):.1f}"
            )
        parts.append(
            f'<path d="{" ".join(lines)}" fill="none" stroke="{_rand.choice(_INKS)}" stroke-width="3.4" '
            f'stroke-linecap="round" transform="translate({x:.1f} {y:.1f}) rotate({_jitter(10):.1f} 8 16) '
            f'skewX({_jitter(8):.1f}) scale({scale:.2f})"/>'
        )
    for _ in range(26):
        parts.append(
            f'<circle cx="{_rand.uniform(4, width - 4):.1f}" cy="{_rand.uniform(4, height - 4):.1f}" '
            f'r="{_rand.uniform(0.7, 1.5):.1f}" fill="{_rand.choice(_INKS)}" opacity="0.6"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def new_captcha() -> tuple[str, str]:
    """A fresh picture: its id and the SVG to show."""
    now = time.monotonic()
    for key in [k for k, (_, exp) in _captchas.items() if exp < now]:
        del _captchas[key]
    while len(_captchas) >= CAPTCHA_KEEP:
        del _captchas[next(iter(_captchas))]
    answer = "".join(_rand.choice("0123456789") for _ in range(CAPTCHA_DIGITS))
    captcha_id = secrets.token_urlsafe(18)
    _captchas[captcha_id] = (answer, now + CAPTCHA_SECONDS)
    return captcha_id, _picture(answer)


def check_captcha(captcha_id: str, answer: str) -> bool:
    """One try per picture: right or wrong, it cannot be used again."""
    found = _captchas.pop(captcha_id, None)
    if found is None:
        return False
    expected, expires = found
    return time.monotonic() <= expires and secrets.compare_digest(expected, answer.strip())


def _key(ip: str, username: str) -> str:
    return f"{ip}|{username.strip().lower()}"


def locked_for(ip: str, username: str) -> int:
    """Seconds this address still has to wait before trying this login again; 0 if it may try."""
    tries = _tries.get(_key(ip, username))
    if tries is None:
        return 0
    return max(0, round(tries.locked_until - time.monotonic()))


def failed(ip: str, username: str) -> None:
    s = get_settings()
    now = time.monotonic()
    window = s.login_lock_minutes * 60
    for key in [k for k, t in _tries.items() if now - t.last > window and t.locked_until < now]:
        del _tries[key]
    tries = _tries.setdefault(_key(ip, username), _Tries())
    tries.failures += 1
    tries.last = now
    if tries.failures >= s.login_max_failures:
        tries.failures = 0
        tries.locked_until = now + window


def succeeded(ip: str, username: str) -> None:
    _tries.pop(_key(ip, username), None)


def reset() -> None:
    """Forget everything; for tests."""
    _captchas.clear()
    _tries.clear()

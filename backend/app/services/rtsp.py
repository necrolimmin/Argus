"""RTSP DESCRIBE check: is the stream there, are the credentials right, which codec.

Asks the camera for the stream description only, without starting video,
so it is fast and cheap.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit


@dataclass
class RtspCheck:
    ok: bool
    error: str = ""  # unreachable | bad_credentials | stream_not_found | rtsp_failed
    codec: str = ""  # H264 | H265 | ...


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _parse_auth(header: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="?([^",]*)"?', header))


async def _request(reader, writer, url: str, cseq: int, auth: str | None) -> tuple[int, dict, str]:
    lines = [f"DESCRIBE {url} RTSP/1.0", f"CSeq: {cseq}", "Accept: application/sdp", "User-Agent: Argus"]
    if auth:
        lines.append(f"Authorization: {auth}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await writer.drain()
    head = await reader.readuntil(b"\r\n\r\n")
    status_line, *header_lines = head.decode(errors="replace").split("\r\n")
    status = int(status_line.split()[1])
    headers: dict[str, list[str]] = {}
    for line in header_lines:
        if ":" in line:
            k, v = line.split(":", 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    length = int(headers.get("content-length", ["0"])[0])
    body = (await reader.readexactly(length)).decode(errors="replace") if length else ""
    return status, headers, body


async def describe(url: str, username: str = "", password: str = "", timeout: float = 6) -> RtspCheck:
    parts = urlsplit(url)
    if parts.username:
        username, password = unquote(parts.username), unquote(parts.password or "")
    host, port = parts.hostname or "", parts.port or 554
    clean = urlunsplit(parts._replace(netloc=f"{host}:{port}"))
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return RtspCheck(False, "unreachable")
    try:
        status, headers, body = await asyncio.wait_for(_request(reader, writer, clean, 1, None), timeout)
        if status == 401 and username:
            challenges = headers.get("www-authenticate", [])
            digest = next((c for c in challenges if c.lower().startswith("digest")), None)
            if digest:
                p = _parse_auth(digest)
                ha1 = _md5(f"{username}:{p.get('realm', '')}:{password}")
                ha2 = _md5(f"DESCRIBE:{clean}")
                response = _md5(f"{ha1}:{p.get('nonce', '')}:{ha2}")
                auth = (
                    f'Digest username="{username}", realm="{p.get("realm", "")}", '
                    f'nonce="{p.get("nonce", "")}", uri="{clean}", response="{response}"'
                )
            else:
                import base64

                auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
            status, headers, body = await asyncio.wait_for(_request(reader, writer, clean, 2, auth), timeout)
        if status == 401:
            return RtspCheck(False, "bad_credentials")
        if status == 404:
            return RtspCheck(False, "stream_not_found")
        if status != 200:
            return RtspCheck(False, "rtsp_failed")
        codec = re.search(r"a=rtpmap:\d+ ([A-Za-z0-9]+)/90000", body)
        return RtspCheck(True, codec=(codec.group(1).upper() if codec else ""))
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, IndexError):
        return RtspCheck(False, "rtsp_failed")
    finally:
        writer.close()

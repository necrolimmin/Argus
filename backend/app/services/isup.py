"""Hikvision devices that connect to Argus by themselves (ISUP 5.0).

The admin creates a device in Argus first: it gets a Device ID and an
encryption key, which the installer types into the device's "Platform
Access" page. The device then dials out to the isup-bridge service from
any network, no port forwarding on its side. Every few seconds this module:

- gives the bridge the Device ID/key pairs that may register;
- marks each ISUP device online or offline and fills in its model and serial;
- adds the cameras of a device that has just connected for the first time
  (one per channel for a recorder);
- tells the bridge which streams to keep open. Sub streams of enabled
  cameras stay open (cheap, the wall and recognition use them); a main
  stream opens when someone watches it and closes a minute after.

The bridge republishes each stream into go2rtc under the camera's usual
stream name, so the wall, fullscreen and the recognizer need nothing special.
"""

import asyncio
import logging
import re
import secrets
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Camera, CameraVendor, Device, DeviceKind, StreamQuality
from app.security import decrypt_secret
from app.services.streams import go2rtc, safe_register, stream_name

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
KEY_RE = re.compile(r"^[A-Za-z0-9]{8,32}$")
# Letters that cannot be misread when typed into a device's web page.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_AUTO_CHANNELS = 64

_state: dict = {}  # last /devices answer from the bridge
_state_at = 0.0
_watched: dict[str, float] = {}  # go2rtc stream name -> last time someone asked for it
_last_keys = ""
_last_want = ""
_last_want_at = 0.0
_kick = asyncio.Event()


def enabled() -> bool:
    return bool(get_settings().isup_public_ip)


def new_device_id() -> str:
    return "ARGUS-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def new_key() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(12))


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(base_url=s.isup_bridge_url, timeout=5, headers={"X-Bridge-Token": s.service_token})


def state() -> dict:
    """The bridge's last report: connected devices, open streams, refusals."""
    return _state if time.monotonic() - _state_at < 30 else {}


def connected(isup_id: str | None) -> dict | None:
    if not isup_id:
        return None
    return next((d for d in state().get("devices", []) if d.get("id") == isup_id), None)


def auto_channels(info: dict) -> list[tuple[int, str]] | None:
    """Channels to add cameras for, or None while the device's details are still coming.

    A recorder registers with one Device ID and has many channels: its IP
    channels from ISAPI (ids 1..N), else the channel count from the SDK.
    """
    if info.get("info") == "pending" and time.time() - float(info.get("since") or 0) < 30:
        return None
    ip = sorted((c for c in info.get("channels") or [] if int(c.get("id") or 0) > 0), key=lambda c: int(c["id"]))
    if ip:
        return [(int(c["id"]), str(c.get("name") or "").strip()[:80]) for c in ip][:MAX_AUTO_CHANNELS]
    total = int(info.get("total") or 0)
    if total > 1:
        start = int(info.get("start") or 1) or 1
        return [(start + i, "") for i in range(min(total, MAX_AUTO_CHANNELS))]
    return [(1, "")]


def want_lines(devices: list[Device], now: float, watched: dict[str, float], live: set[str]) -> list[str]:
    """What the bridge should keep open: "<deviceID> <channel> <0|1> <stream>" lines."""
    idle = get_settings().isup_main_idle_seconds
    lines = []
    for dev in devices:
        if not dev.isup_id or not ID_RE.match(dev.isup_id):
            continue
        for cam in dev.cameras:
            if not cam.enabled:
                continue
            sub = stream_name(cam.id, StreamQuality.sub)
            main = stream_name(cam.id, StreamQuality.main)
            lines.append(f"{dev.isup_id} {cam.channel} 1 {sub}")
            needed = (
                (cam.face_recognition and cam.recognition_stream == StreamQuality.main)
                or now - watched.get(main, 0) < idle
                or main in live
            )
            if needed:
                lines.append(f"{dev.isup_id} {cam.channel} 0 {main}")
    return sorted(lines)


async def _live_streams() -> set[str]:
    """go2rtc streams someone is watching right now."""
    try:
        r = await go2rtc().client.get("/api/streams")
        r.raise_for_status()
        return {name for name, s in (r.json() or {}).items() if (s or {}).get("consumers")}
    except Exception:  # noqa: BLE001
        return set()


async def _add_cameras(dev: Device, info: dict) -> list[Camera]:
    chans = auto_channels(info)
    if chans is None:
        return []
    base = dev.name or dev.isup_id
    added = []
    for channel, name in chans:
        cam = Camera(
            name=(base if len(chans) == 1 else f"{base} · {name or f'CH{channel}'}")[:200],
            channel=channel,
            org_unit_id=dev.org_unit_id,
        )
        dev.cameras.append(cam)
        added.append(cam)
    if len(chans) > 1:
        dev.kind = DeviceKind.recorder
    return added


async def sync_once() -> None:
    global _state, _state_at, _last_keys, _last_want, _last_want_at
    async with _client() as c:
        try:
            r = await c.get("/devices")
            r.raise_for_status()
            _state, _state_at = r.json(), time.monotonic()
        except Exception as exc:  # noqa: BLE001
            log.debug("isup bridge not reachable: %s", exc)
            return

        async with SessionLocal() as session:
            devices = (await session.scalars(select(Device).where(Device.vendor == CameraVendor.isup))).unique().all()

            keys = []
            for dev in devices:
                key = decrypt_secret(dev.password_enc)
                if dev.isup_id and ID_RE.match(dev.isup_id) and KEY_RE.match(key):
                    keys.append(f"{dev.isup_id} {key}")
            body = "\n".join(sorted(keys))
            # The bridge forgets keys when it restarts; it says so with keys_set.
            if body != _last_keys or not _state.get("keys_set"):
                await c.put("/keys", content=body)
                _last_keys = body

            now = datetime.now(timezone.utc)
            seen = {d.get("id"): d for d in _state.get("devices", [])}
            added: list[Camera] = []
            for dev in devices:
                info = seen.get(dev.isup_id)
                dev.online = info is not None
                if info is None:
                    continue
                dev.last_seen_at = now
                dev.model = dev.model or str(info.get("model") or "")[:200]
                dev.serial = dev.serial or str(info.get("serial") or "")[:100]
                dev.firmware = str(info.get("firmware") or dev.firmware)[:200]
                if not dev.cameras:
                    added += await _add_cameras(dev, info)
            await session.commit()
            for cam in added:
                log.info("ISUP device connected, camera added: %s", cam.name)
                await safe_register(cam)

            t = time.time()
            for name, at in list(_watched.items()):
                if t - at > 3600:
                    del _watched[name]
            want = "\n".join(want_lines(devices, t, _watched, await _live_streams()))
        if want != _last_want or t - _last_want_at > 30:
            await c.put("/want", content=want)
            _last_want, _last_want_at = want, t


async def run() -> None:
    while True:
        try:
            await sync_once()
        except Exception:  # noqa: BLE001
            log.exception("isup sync failed")
        _kick.clear()
        try:
            await asyncio.wait_for(_kick.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


async def _has_video(name: str) -> bool:
    try:
        r = await go2rtc().client.get("/api/streams", params={"src": name})
        if r.status_code != 200:
            return False
        return any(p.get("medias") for p in (r.json() or {}).get("producers") or [])
    except Exception:  # noqa: BLE001
        return False


async def touch(cam: Camera, quality: StreamQuality, wait: float = 6) -> None:
    """Someone is about to watch this stream: make sure the device is sending it.

    A main stream is opened only on demand, so the first viewer waits until
    the bridge has started pushing it (usually well under a second).
    """
    name = stream_name(cam.id, quality)
    _watched[name] = time.time()
    if await _has_video(name):
        return
    _kick.set()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        if await _has_video(name):
            return

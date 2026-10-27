"""Camera RTSP links and their registration in go2rtc.

go2rtc keeps one connection per camera stream and shares it between every
browser viewer and the recognizer, so cameras with low connection limits
are not overloaded.
"""

import logging
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Camera, CameraVendor, Device, StreamQuality
from app.security import decrypt_secret

log = logging.getLogger(__name__)

PREFIX = "cam_"


def stream_name(camera_id, quality: StreamQuality) -> str:
    return f"{PREFIX}{camera_id.hex}_{quality.value}"


def _auth(username: str, password: str) -> str:
    if not username:
        return ""
    auth = quote(username, safe="")
    if password:
        auth += ":" + quote(password, safe="")
    return auth + "@"


def with_credentials(url: str, username: str, password: str) -> str:
    parts = urlsplit(url)
    if not username or "@" in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=_auth(username, password) + parts.netloc))


def template_url(vendor: CameraVendor, host: str, port: int, channel: int, quality: StreamQuality,
                 username: str = "", password: str = "") -> str:
    """Stream source for a vendor's standard layout, or "" when it has none.

    Returned links are go2rtc sources: RTSP for most vendors, `dvrip://`
    for XMeye devices.
    """
    main = quality == StreamQuality.main
    auth = _auth(username, password)
    base = f"rtsp://{auth}{host}:{port}"
    if vendor in (CameraVendor.hikvision, CameraVendor.ezviz):
        return f"{base}/Streaming/Channels/{channel}{'01' if main else '02'}"
    if vendor == CameraVendor.dahua:
        return f"{base}/cam/realmonitor?channel={channel}&subtype={0 if main else 1}"
    if vendor == CameraVendor.uniview:
        return f"{base}/unicast/c{channel}/s{0 if main else 1}/live"
    if vendor == CameraVendor.axis:
        extra = "" if main else "&resolution=640x360"
        return f"{base}/axis-media/media.amp?camera={channel}{extra}"
    if vendor == CameraVendor.vigi:
        return f"{base}/stream{1 if main else 2}"
    if vendor == CameraVendor.reolink:
        return f"{base}/h264Preview_{channel:02d}_{'main' if main else 'sub'}"
    if vendor == CameraVendor.dvrip:
        # XMeye counts channels from 0; its service port is 34567 by default.
        dport = port if port != 554 else 34567
        return f"dvrip://{auth}{host}:{dport}?channel={channel - 1}&subtype={0 if main else 1}"
    return ""


def credentials(dev: Device) -> tuple[str, str]:
    """The login/password a device actually uses: its profile's, or its own."""
    if dev.credential is not None:
        return dev.credential.username, decrypt_secret(dev.credential.password_enc)
    return dev.username, decrypt_secret(dev.password_enc)


def rtsp_url(cam: Camera, quality: StreamQuality) -> str:
    dev = cam.device
    username, password = credentials(dev)
    custom = cam.rtsp_main if quality == StreamQuality.main else (cam.rtsp_sub or cam.rtsp_main)
    if custom:
        return with_credentials(custom, username, password)
    return template_url(dev.vendor, dev.host, dev.rtsp_port, cam.channel, quality, username, password)


def restream_url(cam: Camera) -> str:
    """Where the recognizer reads this camera from (through go2rtc)."""
    return f"{get_settings().go2rtc_rtsp_url}/{stream_name(cam.id, cam.recognition_stream)}"


class Go2rtcError(Exception):
    pass


class Go2rtc:
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10)

    async def close(self) -> None:
        await self.client.aclose()

    async def list_streams(self) -> set[str]:
        r = await self.client.get("/api/streams")
        r.raise_for_status()
        return set((r.json() or {}).keys())

    async def put_stream(self, name: str, src: str) -> None:
        r = await self.client.put("/api/streams", params={"name": name, "src": src})
        r.raise_for_status()

    async def delete_stream(self, name: str) -> None:
        r = await self.client.delete("/api/streams", params={"src": name})
        if r.status_code not in (200, 404):
            r.raise_for_status()

    async def register(self, cam: Camera) -> None:
        for q in StreamQuality:
            name = stream_name(cam.id, q)
            await self.delete_stream(name)
            if cam.enabled:
                await self.put_stream(name, rtsp_url(cam, q))

    async def unregister(self, camera_id) -> None:
        for q in StreamQuality:
            await self.delete_stream(stream_name(camera_id, q))

    async def ensure(self, cam: Camera, name: str) -> None:
        if name not in await self.list_streams():
            await self.register(cam)

    def ws_url(self, name: str) -> str:
        base = str(self.client.base_url).rstrip("/")
        return base.replace("http", "ws", 1) + "/api/ws?" + urlencode({"src": name})

    async def webrtc(self, name: str, offer_sdp: str) -> str:
        r = await self.client.post(
            "/api/webrtc",
            params={"src": name},
            content=offer_sdp,
            headers={"Content-Type": "application/sdp"},
        )
        if r.status_code == 404:
            raise LookupError(name)
        if r.status_code >= 400:
            raise Go2rtcError(r.text[:200])
        return r.text

    async def sync(self, session: AsyncSession) -> None:
        """Make go2rtc's stream list match the database.

        Streams added through the API live only in go2rtc's memory, so this
        also restores them after go2rtc restarts.
        """
        cameras = (await session.scalars(select(Camera).where(Camera.enabled))).all()
        wanted = {stream_name(c.id, q): (c, q) for c in cameras for q in StreamQuality}
        existing = {n for n in await self.list_streams() if n.startswith(PREFIX)}
        for name in existing - wanted.keys():
            await self.delete_stream(name)
        for name in wanted.keys() - existing:
            cam, q = wanted[name]
            await self.put_stream(name, rtsp_url(cam, q))


_go2rtc: Go2rtc | None = None


def go2rtc() -> Go2rtc:
    global _go2rtc
    if _go2rtc is None:
        _go2rtc = Go2rtc(get_settings().go2rtc_url)
    return _go2rtc


async def close_go2rtc() -> None:
    global _go2rtc
    if _go2rtc is not None:
        await _go2rtc.close()
        _go2rtc = None


async def safe_register(cam: Camera) -> None:
    # The periodic sync repairs anything that fails here.
    try:
        await go2rtc().register(cam)
    except Exception as exc:  # noqa: BLE001
        log.warning("go2rtc register %s failed: %s", cam.id, exc)


async def safe_unregister(camera_id) -> None:
    try:
        await go2rtc().unregister(camera_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("go2rtc unregister %s failed: %s", camera_id, exc)

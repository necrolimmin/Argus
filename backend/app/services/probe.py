"""Connect to a device before adding it: who it is, which channels, does video work.

Each vendor is asked in its own language where it has one (Hikvision ISAPI,
Dahua CGI), ONVIF otherwise. Whatever the vendor API says, the result is
only "ok" once the RTSP stream itself answers with the given credentials.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.models import CameraVendor, DeviceKind, StreamQuality
from app.services import rtsp
from app.services.onvif import OnvifClient, OnvifError
from app.services.streams import template_url, with_credentials

log = logging.getLogger(__name__)

TEMPLATE_VENDORS = {
    CameraVendor.hikvision,
    CameraVendor.dahua,
    CameraVendor.uniview,
    CameraVendor.axis,
    CameraVendor.vigi,
    CameraVendor.reolink,
    CameraVendor.ezviz,
    CameraVendor.dvrip,
}
MAX_SNAPSHOT = 3 * 1024 * 1024
# Vendor SDK / client ports that people often type instead of the RTSP one.
SDK_PORTS = {8000, 37777, 37778, 34567}


@dataclass
class ProbeChannel:
    channel: int
    name: str = ""
    rtsp_main: str = ""  # set only when the URL is not the vendor template
    rtsp_sub: str = ""
    ip: str = ""  # address of the camera behind a recorder channel, if known


@dataclass
class ProbeResult:
    ok: bool = False
    error: str = ""
    kind: DeviceKind = DeviceKind.camera
    name: str = ""
    model: str = ""
    serial: str = ""
    mac: str = ""
    firmware: str = ""
    codec: str = ""
    # RTSP port as the device reports it; used when the typed one is wrong.
    rtsp_port: int | None = None
    channels: list[ProbeChannel] = field(default_factory=list)
    snapshot: bytes | None = None
    # Non-fatal: e.g. the vendor API is closed but video works.
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProbeTarget:
    vendor: CameraVendor
    host: str = ""
    rtsp_port: int = 554
    http_port: int = 80
    username: str = ""
    password: str = ""
    rtsp_main: str = ""
    rtsp_sub: str = ""
    channel_count: int | None = None  # for recorders whose channels cannot be listed


def _norm_mac(mac: str) -> str:
    return mac.strip().lower().replace("-", ":")


class _ApiError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # unreachable | bad_credentials | api_failed


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    try:
        r = await client.get(url)
    except httpx.HTTPError as exc:
        raise _ApiError("unreachable") from exc
    if r.status_code == 401:
        raise _ApiError("bad_credentials")
    if r.status_code >= 400:
        raise _ApiError("api_failed")
    return r


def _http(t: ProbeTarget) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"http://{t.host}:{t.http_port}",
        auth=httpx.DigestAuth(t.username, t.password),
        timeout=6,
    )


# --- Hikvision ISAPI -----------------------------------------------------------


def _x(el: ET.Element | None, tag: str) -> str:
    found = el.find(f".//{{*}}{tag}") if el is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


async def _hikvision(t: ProbeTarget, res: ProbeResult) -> None:
    async with _http(t) as c:
        info = ET.fromstring((await _get(c, "/ISAPI/System/deviceInfo")).content)
        res.name = _x(info, "deviceName")
        res.model = _x(info, "model")
        res.serial = _x(info, "serialNumber")
        res.mac = _norm_mac(_x(info, "macAddress"))
        res.firmware = _x(info, "firmwareVersion")
        device_type = _x(info, "deviceType").upper()

        names: dict[int, str] = {}
        try:
            streams = ET.fromstring((await _get(c, "/ISAPI/Streaming/channels")).content)
            for sc in streams.iter():
                if not sc.tag.endswith("}StreamingChannel"):
                    continue
                sid = int(_x(sc, "id") or 0)
                if sid % 100 == 1:
                    names[sid // 100] = _x(sc, "channelName")
        except (_ApiError, ET.ParseError, ValueError):
            pass

        ips: dict[int, str] = {}
        if "NVR" in device_type or "DVR" in device_type or len(names) > 1:
            res.kind = DeviceKind.recorder
            try:
                proxy = ET.fromstring((await _get(c, "/ISAPI/ContentMgmt/InputProxy/channels")).content)
                for ch in proxy.iter():
                    if ch.tag.endswith("}InputProxyChannel"):
                        cid = int(_x(ch, "id") or 0)
                        ips[cid] = _x(ch, "ipAddress")
                        names.setdefault(cid, _x(ch, "name"))
            except (_ApiError, ET.ParseError, ValueError):
                pass

        res.channels = [ProbeChannel(channel=n, name=names[n], ip=ips.get(n, "")) for n in sorted(names)]
        try:
            access = ET.fromstring((await _get(c, "/ISAPI/Security/adminAccesses")).content)
            for proto in access.iter():
                if proto.tag.endswith("}AdminAccessProtocol") and _x(proto, "protocol").upper() == "RTSP":
                    res.rtsp_port = int(_x(proto, "portNo")) or None
        except (_ApiError, ET.ParseError, ValueError):
            pass
        first = res.channels[0].channel if res.channels else 1
        for path in (f"/ISAPI/Streaming/channels/{first}02/picture", f"/ISAPI/Streaming/channels/{first}01/picture"):
            try:
                r = await _get(c, path)
                if r.headers.get("content-type", "").startswith("image") and len(r.content) <= MAX_SNAPSHOT:
                    res.snapshot = r.content
                    break
            except _ApiError:
                continue


# --- Dahua CGI -----------------------------------------------------------------


def _kv(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


async def _dahua(t: ProbeTarget, res: ProbeResult) -> None:
    async with _http(t) as c:
        system = _kv((await _get(c, "/cgi-bin/magicBox.cgi?action=getSystemInfo")).text)
        res.serial = system.get("serialNumber", "")
        res.model = system.get("deviceType", "")
        try:
            res.name = _kv((await _get(c, "/cgi-bin/magicBox.cgi?action=getMachineName")).text).get("name", "")
            res.firmware = _kv((await _get(c, "/cgi-bin/magicBox.cgi?action=getSoftwareVersion")).text).get("version", "")
            device_class = _kv((await _get(c, "/cgi-bin/magicBox.cgi?action=getDeviceClass")).text).get("type", "")
        except _ApiError:
            device_class = ""
        try:
            net = _kv((await _get(c, "/cgi-bin/configManager.cgi?action=getConfig&name=Network")).text)
            res.mac = _norm_mac(next((v for k, v in net.items() if k.endswith("PhysicalAddress")), ""))
        except _ApiError:
            pass
        names: dict[int, str] = {}
        try:
            titles = _kv((await _get(c, "/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle")).text)
            for k, v in titles.items():
                m = re.search(r"ChannelTitle\[(\d+)\]\.Name", k)
                if m:
                    names[int(m.group(1)) + 1] = v.strip()
        except _ApiError:
            pass
        if any(x in (device_class + res.model).upper() for x in ("NVR", "DVR", "XVR", "HCVR")) or len(names) > 1:
            res.kind = DeviceKind.recorder
        res.channels = [ProbeChannel(channel=n, name=names[n]) for n in sorted(names)]
        try:
            rtsp_cfg = _kv((await _get(c, "/cgi-bin/configManager.cgi?action=getConfig&name=RTSP")).text)
            res.rtsp_port = int(rtsp_cfg.get("table.RTSP.Port", "0").strip()) or None
        except (_ApiError, ValueError):
            pass
        first = res.channels[0].channel if res.channels else 1
        try:
            r = await _get(c, f"/cgi-bin/snapshot.cgi?channel={first}")
            if r.headers.get("content-type", "").startswith("image") and len(r.content) <= MAX_SNAPSHOT:
                res.snapshot = r.content
        except _ApiError:
            pass


# --- ONVIF ---------------------------------------------------------------------


async def _onvif(t: ProbeTarget, res: ProbeResult, keep_uris: bool) -> None:
    client = OnvifClient(t.host, t.http_port, t.username, t.password)
    try:
        info = await client.describe()
        res.model = " ".join(x for x in (info.manufacturer, info.model) if x)
        res.serial, res.mac, res.firmware = info.serial, _norm_mac(info.mac), info.firmware
        res.channels = [
            ProbeChannel(
                channel=ch.channel,
                name=ch.name,
                rtsp_main=ch.main_uri if keep_uris else "",
                rtsp_sub=ch.sub_uri if keep_uris else "",
            )
            for ch in info.channels
        ]
        if len(res.channels) > 1:
            res.kind = DeviceKind.recorder
        if info.channels:
            uri = await client.snapshot_uri(info.channels[0].main_token)
            if uri:
                res.snapshot = await _fetch_image(uri, t.username, t.password)
    except OnvifError as exc:
        raise _ApiError({"not_onvif": "api_failed"}.get(exc.code, exc.code)) from exc
    finally:
        await client.close()


async def _fetch_image(url: str, username: str, password: str) -> bytes | None:
    for auth in (httpx.DigestAuth(username, password), httpx.BasicAuth(username, password)):
        try:
            async with httpx.AsyncClient(timeout=6, auth=auth) as c:
                r = await c.get(url)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return r.content if len(r.content) <= MAX_SNAPSHOT else None
        except httpx.HTTPError:
            return None
    return None


# --- entry point ---------------------------------------------------------------


async def _tcp_open(host: str, port: int, timeout: float = 4) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def _stream_source(t: ProbeTarget, ch: ProbeChannel, port: int) -> str:
    if ch.rtsp_main:
        return with_credentials(ch.rtsp_main, t.username, t.password)
    return template_url(t.vendor, t.host, port, ch.channel, StreamQuality.main, t.username, t.password)


async def probe(t: ProbeTarget) -> ProbeResult:
    res = ProbeResult()
    vendor = CameraVendor.rtsp if t.vendor == CameraVendor.other else t.vendor

    if vendor in (CameraVendor.rtsp, CameraVendor.http):
        if not t.rtsp_main:
            res.error = "rtsp_main_required"
            return res
        res.channels = [ProbeChannel(channel=1, rtsp_main=t.rtsp_main, rtsp_sub=t.rtsp_sub)]
        if vendor == CameraVendor.http:
            img = await _fetch_image(t.rtsp_main, t.username, t.password)
            res.ok, res.snapshot = True, img
            if img is None and not await _tcp_open(urlsplit(t.rtsp_main).hostname or "", urlsplit(t.rtsp_main).port or 80):
                res.ok, res.error = False, "unreachable"
            return res
    elif vendor == CameraVendor.dvrip:
        port = t.rtsp_port if t.rtsp_port != 554 else 34567
        res.ok = await _tcp_open(t.host, port)
        res.error = "" if res.ok else "unreachable"
        res.channels = [ProbeChannel(channel=n) for n in range(1, (t.channel_count or 1) + 1)]
        if (t.channel_count or 1) > 1:
            res.kind = DeviceKind.recorder
        return res
    else:
        api = {CameraVendor.hikvision: _hikvision, CameraVendor.dahua: _dahua}.get(vendor)
        try:
            if api:
                await api(t, res)
            elif vendor != CameraVendor.ezviz:
                await _onvif(t, res, keep_uris=vendor == CameraVendor.onvif)
        except _ApiError as exc:
            if exc.code == "bad_credentials":
                res.error = "bad_credentials"
                return res
            if vendor == CameraVendor.onvif:
                res.error = {"api_failed": "not_onvif"}.get(exc.code, exc.code)
                return res
            # The device's own API may be closed or on another port; the
            # stream can still work through the vendor template.
            res.warnings.append("api_unavailable")
        except (ET.ParseError, ValueError) as exc:
            log.info("probe %s: unexpected answer: %s", t.host, exc)
            res.warnings.append("api_unavailable")
        if not res.channels:
            res.channels = [ProbeChannel(channel=n) for n in range(1, (t.channel_count or 1) + 1)]
            if len(res.channels) > 1:
                res.kind = DeviceKind.recorder

    # The device knows its own RTSP port better than whoever typed it.
    port = res.rtsp_port or t.rtsp_port
    if port != t.rtsp_port:
        res.warnings.append("rtsp_port_fixed")
    res.rtsp_port = port
    check = await rtsp.describe(_stream_source(t, res.channels[0], port))
    res.codec = check.codec
    if check.ok:
        res.ok = True
    elif res.kind == DeviceKind.recorder and check.error == "stream_not_found":
        # The first recorder channel may simply have no camera plugged in.
        res.ok = True
        res.warnings.append("first_channel_empty")
    elif check.error in ("rtsp_failed", "unreachable") and port in SDK_PORTS and not res.channels[0].rtsp_main:
        res.error = "rtsp_port_wrong"
    else:
        res.error = check.error
    return res

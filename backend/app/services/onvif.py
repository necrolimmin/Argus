"""Minimal ONVIF client: device info, media profiles, stream and snapshot URIs.

Only the handful of SOAP calls Argus needs, over httpx, with WS-Security
digest authentication. Many cameras keep their clock wrong (1970 after a
reboot) and reject tokens whose timestamp is far from their own, so the
token is stamped with the device's time, read first without auth.
"""

import base64
import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx

DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"


class OnvifError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code, detail)
        self.code = code  # unreachable | bad_credentials | not_onvif | onvif_disabled


@dataclass
class OnvifProfile:
    token: str
    name: str
    source: str
    source_name: str
    encoding: str
    width: int
    height: int


@dataclass
class OnvifChannel:
    channel: int
    name: str
    main_uri: str
    sub_uri: str
    main_token: str
    codec: str


@dataclass
class OnvifInfo:
    manufacturer: str = ""
    model: str = ""
    firmware: str = ""
    serial: str = ""
    mac: str = ""
    channels: list[OnvifChannel] = field(default_factory=list)


def strip_credentials(uri: str) -> str:
    parts = urlsplit(uri)
    if "@" not in parts.netloc:
        return uri
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _text(el: ET.Element | None, path: str) -> str:
    found = el.find(path) if el is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


class OnvifClient:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float = 6,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.device_url = f"http://{host}:{port}/onvif/device_service"
        self.username = username
        self.password = password
        self.http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self.offset = timedelta(0)
        self.media_url = ""

    async def close(self) -> None:
        await self.http.aclose()

    def _security(self) -> str:
        if not self.username:
            return ""
        nonce = os.urandom(16)
        created = (datetime.now(timezone.utc) + self.offset).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(
            hashlib.sha1(nonce + created.encode() + self.password.encode()).digest()
        ).decode()
        return (
            '<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-wssecurity-secext-1.0.xsd"><UsernameToken>'
            f"<Username>{_xml_escape(self.username)}</Username>"
            '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-'
            f'token-profile-1.0#PasswordDigest">{digest}</Password>'
            '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-'
            f'message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
            '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-'
            f'utility-1.0.xsd">{created}</Created></UsernameToken></Security>'
        )

    async def _call(self, url: str, body: str, auth: bool = True) -> ET.Element:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f"<s:Header>{self._security() if auth else ''}</s:Header>"
            f"<s:Body>{body}</s:Body></s:Envelope>"
        )
        try:
            r = await self.http.post(
                url, content=envelope, headers={"Content-Type": "application/soap+xml; charset=utf-8"}
            )
        except httpx.HTTPError as exc:
            raise OnvifError("unreachable", str(exc)) from exc
        text = r.text
        # Hikvision ships with ONVIF switched off and says so in plain HTML.
        if r.status_code == 404 and "onvif" in text.lower() and "disabled" in text.lower():
            raise OnvifError("onvif_disabled")
        if r.status_code in (400, 401, 403, 500) and (
            "NotAuthorized" in text or "Unauthorized" in text or "authority" in text.lower()
            or r.status_code == 401
        ):
            raise OnvifError("bad_credentials", text[:200])
        if r.status_code == 404 or "Envelope" not in text:
            raise OnvifError("not_onvif", f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise OnvifError("not_onvif", text[:200])
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as exc:
            raise OnvifError("not_onvif", "bad xml") from exc
        return root.find("{*}Body")

    async def sync_clock(self) -> None:
        body = await self._call(self.device_url, f'<GetSystemDateAndTime xmlns="{DEVICE_NS}"/>', auth=False)
        utc = body.find(".//{*}UTCDateTime")
        if utc is None:
            return
        try:
            device_now = datetime(
                int(_text(utc, "{*}Date/{*}Year")),
                int(_text(utc, "{*}Date/{*}Month")),
                int(_text(utc, "{*}Date/{*}Day")),
                int(_text(utc, "{*}Time/{*}Hour")),
                int(_text(utc, "{*}Time/{*}Minute")),
                int(_text(utc, "{*}Time/{*}Second")),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return
        self.offset = device_now - datetime.now(timezone.utc)

    async def device_information(self) -> dict[str, str]:
        body = await self._call(self.device_url, f'<GetDeviceInformation xmlns="{DEVICE_NS}"/>')
        info = body.find("{*}GetDeviceInformationResponse")
        return {
            "manufacturer": _text(info, "{*}Manufacturer"),
            "model": _text(info, "{*}Model"),
            "firmware": _text(info, "{*}FirmwareVersion"),
            "serial": _text(info, "{*}SerialNumber"),
        }

    async def mac(self) -> str:
        try:
            body = await self._call(self.device_url, f'<GetNetworkInterfaces xmlns="{DEVICE_NS}"/>')
        except OnvifError:
            return ""
        return _text(body, ".//{*}HwAddress").lower()

    async def _media(self) -> str:
        if not self.media_url:
            body = await self._call(
                self.device_url,
                f'<GetCapabilities xmlns="{DEVICE_NS}"><Category>Media</Category></GetCapabilities>',
            )
            self.media_url = _text(body, ".//{*}Media/{*}XAddr") or self.device_url.replace(
                "device_service", "Media"
            )
        return self.media_url

    async def profiles(self) -> list[OnvifProfile]:
        body = await self._call(await self._media(), f'<GetProfiles xmlns="{MEDIA_NS}"/>')
        out = []
        for p in body.iter():
            if not p.tag.endswith("}Profiles"):
                continue
            vsc = p.find("{*}VideoSourceConfiguration")
            enc = p.find("{*}VideoEncoderConfiguration")
            if vsc is None:
                continue
            res = enc.find("{*}Resolution") if enc is not None else None
            out.append(
                OnvifProfile(
                    token=p.get("token", ""),
                    name=_text(p, "{*}Name"),
                    source=_text(vsc, "{*}SourceToken"),
                    source_name=_text(vsc, "{*}Name"),
                    encoding=_text(enc, "{*}Encoding"),
                    width=int(_text(res, "{*}Width") or 0),
                    height=int(_text(res, "{*}Height") or 0),
                )
            )
        return out

    async def stream_uri(self, token: str) -> str:
        body = await self._call(
            await self._media(),
            f'<GetStreamUri xmlns="{MEDIA_NS}"><StreamSetup>'
            f'<Stream xmlns="{SCHEMA_NS}">RTP-Unicast</Stream>'
            f'<Transport xmlns="{SCHEMA_NS}"><Protocol>RTSP</Protocol></Transport>'
            f"</StreamSetup><ProfileToken>{_xml_escape(token)}</ProfileToken></GetStreamUri>",
        )
        return strip_credentials(_text(body, ".//{*}MediaUri/{*}Uri"))

    async def snapshot_uri(self, token: str) -> str:
        try:
            body = await self._call(
                await self._media(),
                f'<GetSnapshotUri xmlns="{MEDIA_NS}"><ProfileToken>{_xml_escape(token)}</ProfileToken></GetSnapshotUri>',
            )
        except OnvifError:
            return ""
        return _text(body, ".//{*}MediaUri/{*}Uri")

    async def channels(self) -> list[OnvifChannel]:
        """One channel per video source; highest resolution is main, lowest is sub."""
        by_source: dict[str, list[OnvifProfile]] = {}
        for p in await self.profiles():
            by_source.setdefault(p.source, []).append(p)
        channels = []
        for i, (source, profiles) in enumerate(by_source.items(), start=1):
            ranked = sorted(profiles, key=lambda p: p.width * p.height, reverse=True)
            main, sub = ranked[0], ranked[-1]
            main_uri = await self.stream_uri(main.token)
            sub_uri = await self.stream_uri(sub.token) if sub is not main else ""
            channels.append(
                OnvifChannel(
                    channel=i,
                    name=main.source_name if len(by_source) > 1 and main.source_name else "",
                    main_uri=main_uri,
                    sub_uri=sub_uri,
                    main_token=main.token,
                    codec=main.encoding,
                )
            )
        return channels

    async def describe(self) -> OnvifInfo:
        await self.sync_clock()
        info = await self.device_information()
        return OnvifInfo(**info, mac=await self.mac(), channels=await self.channels())


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )

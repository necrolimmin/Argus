import asyncio
import hashlib
import re
from datetime import datetime, timezone

import httpx
import pytest

from app.models import DeviceKind, StreamQuality
from app.services import discovery, rtsp
from app.services.onvif import OnvifClient
from app.services.probe import ProbeChannel, ProbeResult
from tests.conftest import add_camera, device_body

SVC = {"X-Service-Token": "svc"}


def test_recorder_channels_units_and_cascade(client, admin, tree):
    body = device_body(
        tree["enterprise"]["id"],
        name="NVR",
        channels=[
            {"channel": 1, "name": "Gate"},
            {"channel": 2, "name": "Warehouse", "org_unit_id": tree["section"]["id"]},
        ],
    )
    dev = client.post("/api/devices", json=body, headers=admin).json()
    assert dev["kind"] == "recorder"
    units = {c["name"]: c["org_unit_id"] for c in dev["cameras"]}
    assert units == {"Gate": tree["enterprise"]["id"], "Warehouse": tree["section"]["id"]}

    # Adding channels skips ones that already exist.
    r = client.post(
        f"/api/devices/{dev['id']}/cameras",
        json={"channels": [{"channel": 2, "name": "dup"}, {"channel": 5, "name": "Yard"}]},
        headers=admin,
    )
    assert [c["channel"] for c in r.json()["cameras"]] == [1, 2, 5]

    # An event on one of its cameras survives deleting the recorder.
    cam_id = dev["cameras"][0]["id"]
    client.post(
        "/api/internal/events",
        data={"camera_id": cam_id, "kind": "unknown", "occurred_at": datetime.now(timezone.utc).isoformat()},
        files={"image": ("s.jpg", b"x")},
        headers=SVC,
    )
    assert client.delete(f"/api/devices/{dev['id']}", headers=admin).status_code == 204
    assert client.get("/api/cameras", headers=admin).json() == []
    events = client.get("/api/events", params={"kind": "unknown"}, headers=admin).json()
    assert len(events) == 1 and events[0]["camera_id"] is None and events[0]["camera_name"] == "Gate"


def test_deleting_last_camera_removes_single_device(client, admin, tree):
    cam = add_camera(client, admin, tree["section"]["id"])
    assert client.delete(f"/api/cameras/{cam['id']}", headers=admin).status_code == 204
    assert client.get("/api/devices", headers=admin).json() == []


def test_credential_profile_drives_stream_credentials(client, admin, tree):
    from app.db import SessionLocal
    from app.models import Camera
    from app.services.streams import rtsp_url

    profile = client.post(
        "/api/credentials", json={"name": "Site A", "username": "viewer", "password": "one"}, headers=admin
    ).json()
    body = device_body(tree["section"]["id"], credential_id=profile["id"], username="", password="")
    dev = client.post("/api/devices", json=body, headers=admin).json()
    assert dev["credential_id"] == profile["id"] and dev["username"] == ""

    async def url():
        async with SessionLocal() as s:
            cam = await s.get(Camera, __import__("uuid").UUID(dev["cameras"][0]["id"]))
            return rtsp_url(cam, StreamQuality.main)

    assert client.portal.call(url).startswith("rtsp://viewer:one@10.0.0.5")
    client.put(f"/api/credentials/{profile['id']}", json={"name": "Site A", "username": "viewer", "password": "two"},
               headers=admin)
    assert client.portal.call(url).startswith("rtsp://viewer:two@")

    listed = client.get("/api/credentials", headers=admin).json()
    assert listed[0]["device_count"] == 1 and "password" not in listed[0]
    assert client.delete(f"/api/credentials/{profile['id']}", headers=admin).status_code == 409


def test_probe_reports_duplicates_and_known_channels(client, admin, tree, monkeypatch):
    existing = client.post(
        "/api/devices", json=device_body(tree["section"]["id"], name="Cam", host="10.0.0.20", serial="SN1"),
        headers=admin,
    ).json()

    async def fake_probe(target):
        return ProbeResult(
            ok=True, kind=DeviceKind.recorder, model="DS-9664NI", serial="SN1",
            channels=[ProbeChannel(1, "Door", ip="10.0.0.20"), ProbeChannel(2, "Yard")],
            snapshot=b"\xff\xd8jpeg",
        )

    monkeypatch.setattr("app.api.devices.probe", fake_probe)
    r = client.post("/api/devices/probe", json={"vendor": "hikvision", "host": "10.0.0.30"}, headers=admin)
    out = r.json()
    assert out["ok"] and out["snapshot"].startswith("data:image/jpeg;base64,")
    assert out["duplicates"] == [{"device_id": existing["id"], "name": "Cam", "reason": "serial"}]
    assert [c["duplicate_of"] for c in out["channels"]] == ["Cam", ""]

    # Sync marks channels the recorder no longer has.
    nvr = client.post(
        "/api/devices",
        json=device_body(tree["section"]["id"], name="NVR", host="10.0.0.30",
                         channels=[{"channel": 1, "name": "Door"}, {"channel": 3, "name": "Gone"}]),
        headers=admin,
    ).json()
    synced = client.post(f"/api/devices/{nvr['id']}/sync", headers=admin).json()
    assert [c["camera_id"] is not None for c in synced["channels"]] == [True, False]
    cams = {c["name"]: c["missing"] for c in client.get("/api/devices", headers=admin).json()[-1]["cameras"]}
    assert cams == {"Door": False, "Gone": True}


def test_bulk_create_from_scan(client, admin, tree, monkeypatch):
    async def fake_probe(target):
        if target.host == "10.0.0.99":
            return ProbeResult(ok=False, error="unreachable")
        return ProbeResult(ok=True, model="DS-2CD", channels=[ProbeChannel(1, "")])

    monkeypatch.setattr("app.api.devices.probe", fake_probe)
    r = client.post(
        "/api/devices/bulk",
        json={
            "targets": [{"vendor": "hikvision", "host": "10.0.0.41"}, {"vendor": "hikvision", "host": "10.0.0.99"}],
            "org_unit_id": tree["section"]["id"],
            "username": "admin",
            "password": "x",
        },
        headers=admin,
    )
    assert [(x["host"], x["ok"], x["error"]) for x in r.json()] == [
        ("10.0.0.41", True, ""), ("10.0.0.99", False, "unreachable")
    ]
    assert [c["name"] for c in client.get("/api/cameras", headers=admin).json()] == ["DS-2CD 10.0.0.41"]


def test_import_preview_and_grouping(client, admin, tree):
    csv_text = (
        "Название;Производитель;IP;Порт;Логин;Пароль;Канал;Подразделение;Распознавание;Направление\n"
        "Gate;hikvision;10.0.1.1;554;admin;x;1;Acme / Tashkent / Plant 1;да;вход\n"
        "Yard;hikvision;10.0.1.1;554;admin;x;2;Acme / Tashkent / Plant 1 / Warehouse;нет;\n"
        "Bad;sony;not an ip;;;;1;Nowhere;;\n"
    )
    r = client.post("/api/devices/import/preview", files={"file": ("c.csv", csv_text.encode())}, headers=admin)
    rows = r.json()
    assert [row["errors"] for row in rows] == [[], [], ["vendor_unknown", "unit_not_found"]]
    assert rows[0]["face_recognition"] and rows[0]["direction"] == "entry"

    r = client.post("/api/devices/import", json={"rows": rows}, headers=admin)
    assert r.json() == {"devices": 1, "cameras": 2, "skipped_rows": [4]}
    dev = client.get("/api/devices", headers=admin).json()[0]
    assert dev["kind"] == "recorder" and [c["channel"] for c in dev["cameras"]] == [1, 2]

    tpl = client.get("/api/devices/import/template", headers=admin)
    assert tpl.status_code == 200 and tpl.content[:2] == b"PK"


def test_scan_marks_known_devices(client, admin, tree, monkeypatch):
    add_camera(client, admin, tree["section"]["id"], host="10.0.0.5")

    async def fake_discover():
        return [discovery.Found(ip="10.0.0.5", vendor="hikvision").as_dict(),
                discovery.Found(ip="10.0.0.6", vendor="dahua", activated=False).as_dict()]

    monkeypatch.setattr("app.services.scan_client.discover", fake_discover)
    found = client.post("/api/scan/discover", headers=admin).json()
    assert [(f["ip"], f["device_name"]) for f in found] == [("10.0.0.5", "Gate"), ("10.0.0.6", "")]
    r = client.post("/api/scan/range", json={"ranges": ["10.0.0.0/16"]}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"] == "range_too_large"


# --- protocol helpers -------------------------------------------------------------


def test_discovery_parsers():
    wsd = (
        b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        b'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Body><d:ProbeMatches><d:ProbeMatch>'
        b"<d:Scopes>onvif://www.onvif.org/name/HIKVISION%20DS-2CD2183 onvif://www.onvif.org/hardware/DS-2CD2183G2-LI "
        b"onvif://www.onvif.org/MAC/A4-14-37-00-00-01</d:Scopes>"
        b"<d:XAddrs>http://192.168.3.52/onvif/device_service</d:XAddrs></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"
    )
    f = discovery.parse_wsd(wsd, "192.168.3.52")
    assert (f.ip, f.vendor, f.model, f.mac, f.http_port) == (
        "192.168.3.52", "hikvision", "DS-2CD2183G2-LI", "a4:14:37:00:00:01", 80
    )

    sadp = (
        b"<?xml version='1.0'?><ProbeMatch><DeviceDescription>DS-9664NI-I8</DeviceDescription>"
        b"<DeviceSN>DS-9664NI-I81620SN</DeviceSN><MAC>a4-14-37-00-00-02</MAC><IPv4Address>192.168.3.100</IPv4Address>"
        b"<HttpPort>80</HttpPort><Activated>false</Activated></ProbeMatch>"
    )
    f = discovery.parse_sadp(sadp)
    assert (f.ip, f.vendor, f.model, f.activated, f.http_port) == ("192.168.3.100", "hikvision", "DS-9664NI-I8", False, 80)

    payload = (
        b'{"method":"client.notifyDevInfo","params":{"deviceInfo":{"DeviceType":"DHI-NVR5864",'
        b'"IPv4Address":{"IPAddress":"192.168.3.110"},"Mac":"3c:ef:8c:00:00:03","SerialNo":"7J0","Init":1}}}'
    )
    f = discovery.parse_dahua(discovery.dahua_probe()[:32] + payload)
    assert (f.ip, f.model, f.activated) == ("192.168.3.110", "DHI-NVR5864", False)

    assert discovery.parse_ranges(["10.1.1.10-12", "10.1.1.12", "10.1.2.0/30"]) == [
        "10.1.1.10", "10.1.1.11", "10.1.1.12", "10.1.2.1", "10.1.2.2"
    ]
    with pytest.raises(OverflowError):
        discovery.parse_ranges(["10.0.0.0/16"])

    # The ways people actually type ranges.
    for typed in ("10.1.1.10 - 10.1.1.12", "10.1.1.10 – 10.1.1.12", "10.1.1.10 - 12"):
        assert discovery.parse_ranges([typed]) == ["10.1.1.10", "10.1.1.11", "10.1.1.12"], typed
    assert len(discovery.parse_ranges(["10.1.1.*"])) == 254
    assert len(discovery.parse_ranges(["10.1.1"])) == 254
    assert discovery.parse_ranges(["10.1.1.5 10.1.1.7; 10.1.1.9"]) == ["10.1.1.5", "10.1.1.7", "10.1.1.9"]
    with pytest.raises(ValueError):
        discovery.parse_ranges(["camera"])


ONVIF_REPLIES = {
    "GetSystemDateAndTime": "<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:UTCDateTime>"
    "<tt:Date><tt:Year>1970</tt:Year><tt:Month>1</tt:Month><tt:Day>1</tt:Day></tt:Date>"
    "<tt:Time><tt:Hour>5</tt:Hour><tt:Minute>0</tt:Minute><tt:Second>0</tt:Second></tt:Time>"
    "</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>",
    "GetDeviceInformation": "<tds:GetDeviceInformationResponse><tds:Manufacturer>Uniview</tds:Manufacturer>"
    "<tds:Model>NVR302</tds:Model><tds:FirmwareVersion>B2.0</tds:FirmwareVersion>"
    "<tds:SerialNumber>210235</tds:SerialNumber></tds:GetDeviceInformationResponse>",
    "GetNetworkInterfaces": "<tds:GetNetworkInterfacesResponse><tds:NetworkInterfaces><tt:Info>"
    "<tt:HwAddress>48:EA:63:00:00:04</tt:HwAddress></tt:Info></tds:NetworkInterfaces></tds:GetNetworkInterfacesResponse>",
    "GetCapabilities": "<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media>"
    "<tt:XAddr>http://cam/onvif/media</tt:XAddr></tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>",
    "GetProfiles": "<trt:GetProfilesResponse>"
    + "".join(
        f'<trt:Profiles token="p{src}{q}"><tt:Name>p{src}{q}</tt:Name>'
        f"<tt:VideoSourceConfiguration><tt:Name>Door {src}</tt:Name><tt:SourceToken>vs{src}</tt:SourceToken></tt:VideoSourceConfiguration>"
        f"<tt:VideoEncoderConfiguration><tt:Encoding>H265</tt:Encoding><tt:Resolution><tt:Width>{w}</tt:Width>"
        f"<tt:Height>{h}</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></trt:Profiles>"
        for src in (1, 2)
        for q, w, h in (("s", 640, 360), ("m", 2560, 1440))
    )
    + "</trt:GetProfilesResponse>",
}


def _onvif_handler(seen: list):
    def handle(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        op = re.search(r"<(\w+) xmlns=\"http://www\.onvif\.org/ver10/(?:device|media)/wsdl\"", body).group(1)
        seen.append((op, "UsernameToken" in body, re.search(r"<Created[^>]*>([^<]+)", body)))
        if op == "GetStreamUri":
            token = re.search(r"<ProfileToken>(\w+)<", body).group(1)
            inner = f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>rtsp://admin:pw@cam:554/{token}</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>"
        else:
            inner = ONVIF_REPLIES[op]
        xml = (
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
            'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
            f"<s:Body>{inner}</s:Body></s:Envelope>"
        )
        return httpx.Response(200, text=xml)

    return handle


def test_onvif_client_groups_channels_and_uses_device_clock():
    seen = []
    client = OnvifClient("cam", 80, "admin", "pw", transport=httpx.MockTransport(_onvif_handler(seen)))

    info = asyncio.run(client.describe())
    assert (info.manufacturer, info.model, info.serial, info.mac) == ("Uniview", "NVR302", "210235", "48:ea:63:00:00:04")
    assert [(c.channel, c.name, c.main_uri, c.sub_uri) for c in info.channels] == [
        (1, "Door 1", "rtsp://cam:554/p1m", "rtsp://cam:554/p1s"),
        (2, "Door 2", "rtsp://cam:554/p2m", "rtsp://cam:554/p2s"),
    ]
    # The clock call goes without auth; later calls are stamped in the device's 1970.
    assert seen[0][:2] == ("GetSystemDateAndTime", False)
    assert seen[1][1] and seen[1][2].group(1).startswith("1970-01-01T05:00")


def test_rtsp_describe_with_digest():
    async def scenario():
        async def handle(reader, writer):
            # Closing matters: the server's shutdown waits for every connection.
            try:
                await serve(reader, writer)
            finally:
                writer.close()

        async def serve(reader, writer):
            while True:
                try:
                    head = (await reader.readuntil(b"\r\n\r\n")).decode()
                except (asyncio.IncompleteReadError, ConnectionError):
                    return
                cseq = re.search(r"CSeq: (\d+)", head).group(1)
                auth = re.search(r"Authorization: (.+)\r\n", head)
                ok = False
                if auth:
                    resp = re.search(r'response="(\w+)"', auth.group(1)).group(1)
                    uri = re.search(r'uri="([^"]+)"', auth.group(1)).group(1)
                    ha1 = hashlib.md5(b"admin:cam:secret").hexdigest()
                    ha2 = hashlib.md5(f"DESCRIBE:{uri}".encode()).hexdigest()
                    ok = resp == hashlib.md5(f"{ha1}:n1:{ha2}".encode()).hexdigest()
                if ok:
                    sdp = "v=0\r\nm=video 0 RTP/AVP 96\r\na=rtpmap:96 H265/90000\r\n"
                    writer.write(f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nContent-Length: {len(sdp)}\r\n\r\n{sdp}".encode())
                else:
                    writer.write(
                        f'RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\nWWW-Authenticate: Digest realm="cam", nonce="n1"\r\n\r\n'.encode()
                    )
                await writer.drain()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            good = await rtsp.describe(f"rtsp://127.0.0.1:{port}/Streaming/Channels/101", "admin", "secret")
            bad = await rtsp.describe(f"rtsp://127.0.0.1:{port}/Streaming/Channels/101", "admin", "nope")
        closed = await rtsp.describe(f"rtsp://127.0.0.1:{port}/x", timeout=1)
        return good, bad, closed

    good, bad, closed = asyncio.run(scenario())
    assert (good.ok, good.codec) == (True, "H265")
    assert (bad.ok, bad.error) == (False, "bad_credentials")
    assert (closed.ok, closed.error) == (False, "unreachable")


def test_probe_uses_rtsp_port_reported_by_device(monkeypatch):
    import asyncio

    from app.models import CameraVendor
    from app.services import probe as probe_mod
    from app.services.rtsp import RtspCheck

    async def fake_dahua(t, res):
        res.channels = [ProbeChannel(channel=1), ProbeChannel(channel=2)]
        res.kind = probe_mod.DeviceKind.recorder
        res.rtsp_port = 554

    urls = []

    async def fake_describe(url, *a, **kw):
        urls.append(url)
        return RtspCheck(ok=":554/" in url, error="" if ":554/" in url else "rtsp_failed")

    monkeypatch.setattr(probe_mod, "_dahua", fake_dahua)
    monkeypatch.setattr(probe_mod.rtsp, "describe", fake_describe)
    target = probe_mod.ProbeTarget(vendor=CameraVendor.dahua, host="10.0.0.9", rtsp_port=37777,
                                   username="admin", password="x")
    res = asyncio.run(probe_mod.probe(target))
    assert res.ok and res.rtsp_port == 554 and "rtsp_port_fixed" in res.warnings

    # Without the device saying otherwise, an SDK port gets a precise error.
    async def silent_dahua(t, res):
        res.channels = [ProbeChannel(channel=1)]

    monkeypatch.setattr(probe_mod, "_dahua", silent_dahua)
    res = asyncio.run(probe_mod.probe(target))
    assert not res.ok and res.error == "rtsp_port_wrong"

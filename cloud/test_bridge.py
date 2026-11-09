"""The bridge's stream handling with a fake cloud relay (no network, no cloud).

    cd cloud && python -m pytest -q test_bridge.py
"""

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import bridge
from test_media import _decodes, _encode, needs_ffmpeg


class FakeRelay:
    """Stands in for pyezvizapi's VtmStreamClient: plays back prepared packets."""

    packets: list[bytes] = []
    opened: list[str] = []

    def __init__(self, url, timeout=None, socket_factory=None):
        self.url = url
        FakeRelay.opened.append(url)

    def start(self):
        return SimpleNamespace(result=0)

    def iter_packets(self):
        for body in FakeRelay.packets:
            yield SimpleNamespace(encrypted=False, body=body)
            time.sleep(0.002)
        raise OSError("VTM socket closed while reading packet")

    def close(self):
        pass


class FakePump:
    made: list["FakePump"] = []

    def __init__(self, target, fmt):
        self.target, self.fmt, self.data = target, fmt, bytearray()
        FakePump.made.append(self)

    def alive(self):
        return True

    def put(self, data):
        self.data += data

    def close(self):
        pass


@pytest.fixture
def br(monkeypatch):
    FakeRelay.packets, FakeRelay.opened, FakePump.made = [], [], []
    monkeypatch.setattr(bridge, "VtmStreamClient", FakeRelay)
    monkeypatch.setattr(bridge, "Pump", FakePump)
    monkeypatch.setattr(bridge, "stream_url",
                        lambda acc, serial, channel, sub: f"ysproto://relay:8554/live?dev={serial}&chn={channel}"
                                                          f"&stream={2 if sub else 1}")
    b = bridge.Bridge()
    monkeypatch.setattr(bridge, "BRIDGE", b)
    yield b
    b.set_want([])


def _wait(cond, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


WANT = {"target": "cam_ab_sub", "account": "a1", "serial": "Q123", "channel": 1, "sub": True}


@needs_ffmpeg
def test_ps_stream_is_published(br):
    ps = _encode("h264", "vob", extra=["-an"])
    FakeRelay.packets = [ps[i:i + 1400] for i in range(0, len(ps), 1400)]
    br.set_want([WANT])
    time.sleep(0.3)
    assert br.report()["streams"]["cam_ab_sub"]["state"] == "waiting"  # no session yet
    br.set_accounts({"a1": {"provider": "hik", "api": "api.hik-connect.com", "session_id": "x"}})
    assert _wait(lambda: br.report()["streams"]["cam_ab_sub"]["state"] == "playing")
    assert _wait(lambda: len(FakePump.made[0].data) > len(ps) * 0.8)
    pump = FakePump.made[0]
    assert pump.target == "cam_ab_sub" and pump.fmt == "h264"
    assert _decodes(bytes(pump.data), "h264") >= 25
    assert "stream=2" in FakeRelay.opened[0]


def test_encrypted_video_is_reported(br):
    start = bytes([0, 0, 0, 1])
    payload = (start + bytes([0x67, 0xD3, 0x11]) + start + bytes([0x65]) + bytes([0x88]) * 40) * 3
    pes = bytes([0, 0, 1, 0xE0]) + (3 + len(payload)).to_bytes(2, "big") + bytes([0x80, 0, 0]) + payload
    pack = bytes([0, 0, 1, 0xBA, 0x44]) + bytes(8) + bytes([0xF8])
    FakeRelay.packets = [pack + pes] * 3
    br.set_accounts({"a1": {"provider": "ezviz", "api": "apiieu.ezvizlife.com", "session_id": "x"}})
    br.set_want([WANT])
    assert _wait(lambda: br.report()["streams"]["cam_ab_sub"]["state"] == "encrypted")
    assert not FakePump.made


def test_ended_session_is_reported_and_renewed(br, monkeypatch):
    def ended(acc, serial, channel, sub):
        raise bridge.StreamError("session")

    monkeypatch.setattr(bridge, "stream_url", ended)
    br.set_accounts({"a1": {"provider": "hik", "api": "api.hik-connect.com", "session_id": "old"}})
    br.set_want([WANT])
    assert _wait(lambda: br.report()["expired"] == ["a1"])
    br.set_accounts({"a1": {"provider": "hik", "api": "api.hik-connect.com", "session_id": "new"}})
    assert br.report()["expired"] == []


def test_sub_falls_back_to_main(br, monkeypatch):
    def no_sub(acc, serial, channel, sub):
        if sub:
            raise bridge.StreamError("failed", "no video from the device")
        return "ysproto://relay:8554/live?stream=1"

    monkeypatch.setattr(bridge, "stream_url", no_sub)
    br.set_accounts({"a1": {"provider": "hik", "api": "api.hik-connect.com", "session_id": "x"}})
    br.set_want([WANT])
    assert _wait(lambda: br.report()["streams"]["cam_ab_sub"]["sub_fallback"], seconds=15)


def test_want_changes_stop_streams(br):
    br.set_accounts({"a1": {"provider": "hik", "api": "api.hik-connect.com", "session_id": "x"}})
    br.set_want([WANT, {**WANT, "target": "cam_ab_main", "sub": False}])
    assert set(br.report()["streams"]) == {"cam_ab_sub", "cam_ab_main"}
    br.set_want([WANT])
    assert set(br.report()["streams"]) == {"cam_ab_sub"}
    br.set_want([{**WANT, "target": "bad name!"}])
    assert br.report()["streams"] == {}


def test_api_needs_token(br, monkeypatch):
    monkeypatch.setattr(bridge, "API_TOKEN", "t0k")
    server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(base + "/health")) == {"ok": True}
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/state")
        assert err.value.code == 403
        req = urllib.request.Request(base + "/accounts", method="PUT", headers={"X-Bridge-Token": "t0k"},
                                     data=json.dumps({"a1": {"provider": "hik", "session_id": "s"}}).encode())
        urllib.request.urlopen(req)
        req = urllib.request.Request(base + "/state", headers={"X-Bridge-Token": "t0k"})
        assert json.load(urllib.request.urlopen(req))["accounts_set"] is True
    finally:
        server.shutdown()


def test_session_sign_and_find():
    import base64

    claims = base64.urlsafe_b64encode(json.dumps({"s": "abc"}).encode()).decode().rstrip("=")
    assert bridge._session_sign(f"h.{claims}.sig") == "abc"
    with pytest.raises(bridge.StreamError):
        bridge._session_sign("not-a-jwt")
    res = [{"deviceSerial": "N1", "localIndex": "0"}, {"deviceSerial": "N1", "localIndex": "3"},
           {"deviceSerial": "C1", "localIndex": "1"}]
    assert bridge._find(res, "N1", 3)["localIndex"] == "3"
    assert bridge._find(res, "N1", 2) is None
    assert bridge._find(res, "C1", 1)["deviceSerial"] == "C1"


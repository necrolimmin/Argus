import time

import httpx
import pytest

from app.models import StreamQuality
from app.services import isup
from app.services.streams import PUSH_SOURCE, stream_name


class FakeBridge:
    """Stands in for the isup-bridge service: answers /devices, records /keys and /want."""

    def __init__(self):
        self.devices = []
        self.keys_set = False
        self.keys = ""
        self.want = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Bridge-Token"] == "svc"
        if request.method == "GET" and request.url.path == "/devices":
            return httpx.Response(200, json={"keys_set": self.keys_set, "devices": self.devices,
                                             "streams": [], "rejected": [{"id": "STRANGER-1", "reason": "unknown",
                                                                          "at": int(time.time())}]})
        if request.method == "PUT" and request.url.path == "/keys":
            self.keys, self.keys_set = request.content.decode(), True
            return httpx.Response(200, json={})
        if request.method == "PUT" and request.url.path == "/want":
            self.want = request.content.decode()
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def bridge(monkeypatch):
    fake = FakeBridge()
    monkeypatch.setattr(isup, "_client", lambda: httpx.AsyncClient(
        base_url="http://bridge", transport=httpx.MockTransport(fake.handler), headers={"X-Bridge-Token": "svc"}))

    async def nobody_watching():
        return set()

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(isup, "live_streams", nobody_watching)
    monkeypatch.setattr(isup, "safe_register", nothing)
    monkeypatch.setattr(isup, "_last_keys", "")
    monkeypatch.setattr(isup, "_last_want", "")
    monkeypatch.setattr(isup, "_watched", {})
    return fake


def _sync(client):
    client.portal.call(isup.sync_once)


def test_create_connections_and_read_key(client, admin, tree):
    r = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"], "count": 3, "name": "Gate"},
                    headers=admin)
    assert r.status_code == 201, r.text
    made = r.json()
    ids = [m["device"]["isup_id"] for m in made]
    assert len(set(ids)) == 3 and all(isup.ID_RE.match(i) and i.startswith("ARGUS-") for i in ids)
    assert all(isup.KEY_RE.match(m["key"]) for m in made)
    assert [m["device"]["name"] for m in made] == ["Gate 1", "Gate 2", "Gate 3"]
    assert all(m["device"]["vendor"] == "isup" and m["device"]["cameras"] == [] for m in made)

    key = client.get(f"/api/devices/{made[0]['device']['id']}/isup-key", headers=admin).json()
    assert key == {"device_id": ids[0], "key": made[0]["key"]}

    # A device the installer already set up keeps its own ID and key.
    r = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"], "device_id": "SHOP-7",
                                               "key": "abcd1234"}, headers=admin)
    assert r.status_code == 201 and r.json()[0]["key"] == "abcd1234"
    r = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"], "device_id": "SHOP-7"},
                    headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "isup_id_taken"
    r = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"], "key": "short"}, headers=admin)
    assert r.status_code == 422


def test_connected_recorder_gets_cameras_and_streams(client, admin, tree, bridge):
    made = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"], "name": "NVR"},
                       headers=admin).json()[0]
    dev_id, isup_id, key = made["device"]["id"], made["device"]["isup_id"], made["key"]

    # Not connected yet: the bridge learns the key, the device stays offline.
    _sync(client)
    assert bridge.keys == f"{isup_id} {key}"
    dev = client.get("/api/devices", headers=admin).json()[0]
    assert dev["online"] is False and dev["cameras"] == []
    assert bridge.want == ""

    # It connects as a recorder with two IP channels.
    bridge.devices = [{"id": isup_id, "serial": "DS-7608", "model": "DS-7608NI", "firmware": "V4.1", "info": "ok",
                       "since": int(time.time()), "total": 8, "start": 1,
                       "channels": [{"id": 2, "name": "Yard", "online": True},
                                    {"id": 1, "name": "Gate", "online": True}]}]
    _sync(client)
    dev = client.get("/api/devices", headers=admin).json()[0]
    assert dev["online"] is True and dev["kind"] == "recorder" and dev["model"] == "DS-7608NI"
    assert [(c["channel"], c["name"]) for c in dev["cameras"]] == [(1, "NVR · Gate"), (2, "NVR · Yard")]
    assert all(c["org_unit_id"] == tree["section"]["id"] for c in dev["cameras"])

    # Sub streams always; a main stream only while someone watches.
    _sync(client)
    cams = {c["channel"]: c["id"] for c in dev["cameras"]}
    import uuid

    sub = {f"{isup_id} {ch} 1 {stream_name(uuid.UUID(cid), StreamQuality.sub)}" for ch, cid in cams.items()}
    assert set(bridge.want.splitlines()) == sub
    main = stream_name(uuid.UUID(cams[1]), StreamQuality.main)
    isup._watched[main] = time.time()
    _sync(client)
    assert f"{isup_id} 1 0 {main}" in bridge.want.splitlines()

    # Refreshing reads the channels from the bridge, not from an address.
    r = client.post(f"/api/devices/{dev_id}/sync", headers=admin).json()
    assert r["ok"] is True and [c["camera_id"] is not None for c in r["channels"]] == [True, True]

    # Deleting the device takes its key away from the bridge.
    assert client.delete(f"/api/devices/{dev_id}", headers=admin).status_code == 204
    _sync(client)
    assert bridge.keys == ""

    info = client.get("/api/devices/isup", headers=admin).json()
    assert info["refused"][0]["device_id"] == "STRANGER-1"


def test_unconnected_device_cannot_be_refreshed(client, admin, tree):
    made = client.post("/api/devices/isup", json={"org_unit_id": tree["section"]["id"]}, headers=admin).json()[0]
    r = client.post(f"/api/devices/{made['device']['id']}/sync", headers=admin).json()
    assert r["ok"] is False and r["error"] == "isup_not_connected"


def test_auto_channels_and_push_source():
    assert isup.auto_channels({"info": "pending", "since": time.time()}) is None
    assert isup.auto_channels({"info": "failed", "total": 1}) == [(1, "")]
    assert isup.auto_channels({"info": "ok", "total": 4, "start": 33}) == [(33, ""), (34, ""), (35, ""), (36, "")]
    assert PUSH_SOURCE.startswith("rtsp://127.0.0.1:1/")

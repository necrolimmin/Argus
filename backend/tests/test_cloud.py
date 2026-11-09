import json
import time

import httpx
import pytest

from app.services import cloud, cloud_api


class FakeCloud:
    """The Hik-Connect / EZVIZ API as far as Argus uses it."""

    def __init__(self):
        self.password_md5 = "5f4dcc3b5aa765d61d8327deb882cf99"  # md5("password")
        self.two_step = False
        self.code_sent = 0
        self.logins = []
        self.region = "apiieu.hik-connect.com"
        self.known_on = {"api.hik-connect.com", "apiieu.hik-connect.com"}
        self.devices = [
            {"deviceSerial": "NVR001", "name": "Склад NVR", "deviceType": "DS-7608NI", "status": 1},
            {"deviceSerial": "CAM002", "name": "Door", "deviceType": "DS-2CD1043", "status": 2},
        ]
        self.resources = [
            {"deviceSerial": "NVR001", "localIndex": "0", "resourceName": "NVR"},
            {"deviceSerial": "NVR001", "localIndex": "1", "resourceName": "Ворота"},
            {"deviceSerial": "NVR001", "localIndex": "2", "resourceName": ""},
            {"deviceSerial": "CAM002", "localIndex": "1", "resourceName": "Door"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if path.startswith("/v3/users/login/"):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            self.logins.append((host, form))
            if host not in self.known_on:
                return httpx.Response(200, json={"meta": {"code": 1013}})
            if host != self.region:
                return httpx.Response(200, json={"meta": {"code": 1100}, "loginArea": {"apiDomain": self.region}})
            if form["password"] != self.password_md5:
                return httpx.Response(200, json={"meta": {"code": 1014}})
            if self.two_step and form.get("smsCode") != "123456":
                return httpx.Response(200, json={"meta": {"code": 6002 if not form.get("smsCode") else 1012}})
            return httpx.Response(200, json={"meta": {"code": 200},
                                             "loginSession": {"sessionId": "h.eyJzIjoiYWJjIn0.s", "rfSessionId": "rf1"},
                                             "loginArea": {"apiDomain": self.region}})
        if path == "/v3/sms/nologin/checkcode":
            self.code_sent += 1
            return httpx.Response(200, json={"meta": {"code": 200}})
        if path == "/v3/configurations/system/info":
            return httpx.Response(200, json={"meta": {"code": 200},
                                             "systemConfigInfo": {"authAddr": "https://ieuauth.hik-connect.com"}})
        assert host == self.region, f"API call to {host}"
        assert request.headers["sessionId"].startswith("h.")
        if path == "/v3/userdevices/v1/devices/pagelist":
            return httpx.Response(200, json={"meta": {"code": 200}, "deviceInfos": self.devices,
                                             "statusInfos": {"CAM002": {"isEncrypt": 1}}, "page": {"hasNext": False}})
        if path == "/v3/userdevices/v1/resources/pagelist":
            return httpx.Response(200, json={"meta": {"code": 200}, "resourceInfos": self.resources,
                                             "page": {"hasNext": False}})
        return httpx.Response(404)


class FakeBridge:
    def __init__(self):
        self.accounts = {}
        self.want = []
        self.streams = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Bridge-Token"] == "svc"
        if request.method == "GET" and request.url.path == "/state":
            return httpx.Response(200, json={"accounts_set": bool(self.accounts), "streams": self.streams,
                                             "expired": []})
        if request.url.path == "/accounts":
            self.accounts = json.loads(request.content)
        elif request.url.path == "/want":
            self.want = json.loads(request.content)
        return httpx.Response(200, json={})


@pytest.fixture
def cloud_fake(monkeypatch):
    fake = FakeCloud()
    monkeypatch.setattr(cloud_api, "transport", httpx.MockTransport(fake.handler))
    for d in (cloud._sessions, cloud._login_failed_at, cloud._listed_at, cloud._watched):
        d.clear()
    return fake


@pytest.fixture
def bridge(monkeypatch):
    fake = FakeBridge()
    monkeypatch.setattr(cloud, "_client", lambda: httpx.AsyncClient(
        base_url="http://bridge", transport=httpx.MockTransport(fake.handler), headers={"X-Bridge-Token": "svc"}))

    async def nobody_watching():
        return set()

    monkeypatch.setattr(cloud, "live_streams", nobody_watching)
    monkeypatch.setattr(cloud, "_last_accounts", "")
    monkeypatch.setattr(cloud, "_last_want", "")
    return fake


ACCOUNT = {"provider": "hik", "login": "owner@example.com", "password": "password", "name": "Office"}


def test_login_follows_region_and_keeps_password_secret(client, admin, cloud_fake):
    r = client.post("/api/cloud/accounts", json={**ACCOUNT, "password": "wrong"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "cloud_bad_login"
    r = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin)
    assert r.status_code == 201, r.text
    acc = r.json()
    assert acc["login"] == "owner@example.com" and acc["error"] == "" and "password" not in acc
    hosts = [h for h, _ in cloud_fake.logins[-2:]]
    assert hosts == ["api.hik-connect.com", "apiieu.hik-connect.com"]  # redirected to its region
    assert cloud_fake.logins[-1][1]["password"] == cloud_fake.password_md5  # never the password itself
    r = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "cloud_account_exists"
    info = client.get("/api/cloud", headers=admin).json()
    assert [a["name"] for a in info["accounts"]] == ["Office"] and info["bridge"] is False


def test_unknown_on_global_cloud_tries_the_cis_one(client, admin, cloud_fake):
    cloud_fake.known_on = {"api.hik-connectru.com"}
    cloud_fake.region = "api.hik-connectru.com"
    r = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin)
    assert r.status_code == 201, r.text
    assert [h for h, _ in cloud_fake.logins] == ["api.hik-connect.com", "api.hik-connectru.com"]


def test_two_step_login(client, admin, cloud_fake):
    cloud_fake.two_step = True
    r = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "cloud_needs_code"
    assert cloud_fake.code_sent == 1
    r = client.post("/api/cloud/accounts", json={**ACCOUNT, "code": "000000"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "cloud_bad_code"
    r = client.post("/api/cloud/accounts", json={**ACCOUNT, "code": "123456"}, headers=admin)
    assert r.status_code == 201, r.text
    # The same "phone" on both attempts, or the code would not count.
    codes = {f["featureCode"] for _, f in cloud_fake.logins}
    assert len(codes) == 1


def test_never_sends_the_password_elsewhere(cloud_fake):
    cloud_fake.region = "evil.example.com"
    with pytest.raises(cloud_api.CloudError) as err:
        import asyncio

        asyncio.run(cloud_api.login("hik", "a", "password", "f" * 32))
    assert err.value.code == "cloud_bad_server"
    assert all(h.endswith(".hik-connect.com") for h, _ in cloud_fake.logins)


def test_list_and_add_cameras(client, admin, tree, cloud_fake):
    acc = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin).json()
    devs = client.get(f"/api/cloud/accounts/{acc['id']}/devices", headers=admin).json()
    nvr = next(d for d in devs if d["serial"] == "NVR001")
    cam = next(d for d in devs if d["serial"] == "CAM002")
    assert [c["channel"] for c in nvr["channels"]] == [1, 2] and nvr["online"] is True
    assert cam["online"] is False and cam["encrypted"] is True and cam["channels"][0]["channel"] == 1

    unit = tree["section"]["id"]
    r = client.post(f"/api/cloud/accounts/{acc['id']}/add", headers=admin,
                    json={"org_unit_id": unit, "items": [{"serial": "NVR001", "channels": [1, 2]},
                                                         {"serial": "CAM002", "channels": [1]}]})
    assert r.status_code == 200, r.text
    made = {d["serial"]: d for d in r.json()}
    assert made["NVR001"]["kind"] == "recorder" and made["NVR001"]["vendor"] == "cloud"
    assert [c["name"] for c in made["NVR001"]["cameras"]] == ["Склад NVR · Ворота", "Склад NVR · CH2"]
    assert [c["name"] for c in made["CAM002"]["cameras"]] == ["Door"]
    assert made["CAM002"]["cloud_account_id"] == acc["id"]

    # Adding again changes nothing; the list now shows what is in Argus.
    client.post(f"/api/cloud/accounts/{acc['id']}/add", headers=admin,
                json={"org_unit_id": unit, "items": [{"serial": "NVR001", "channels": [1, 2]}]})
    assert len(client.get("/api/devices", headers=admin).json()) == 2
    devs = client.get(f"/api/cloud/accounts/{acc['id']}/devices", headers=admin).json()
    assert all(c["camera_id"] for d in devs for c in d["channels"])

    # Editing keeps it a cloud device; sync reads the account.
    dev = made["CAM002"]
    r = client.put(f"/api/devices/{dev['id']}", headers=admin,
                   json={"name": "Front door", "org_unit_id": unit, "host": "1.2.3.4", "rtsp_port": 554,
                         "http_port": 80, "username": "", "password": ""})
    assert r.status_code == 200 and r.json()["host"] == "" and r.json()["name"] == "Front door"
    sync = client.post(f"/api/devices/{made['NVR001']['id']}/sync", headers=admin).json()
    assert sync["ok"] and [c["channel"] for c in sync["channels"]] == [1, 2]

    r = client.delete(f"/api/cloud/accounts/{acc['id']}", headers=admin)
    assert r.status_code == 204
    assert client.get("/api/devices", headers=admin).json() == []


def test_bridge_gets_sessions_and_only_needed_streams(client, admin, tree, cloud_fake, bridge):
    acc = client.post("/api/cloud/accounts", json=ACCOUNT, headers=admin).json()
    made = client.post(f"/api/cloud/accounts/{acc['id']}/add", headers=admin,
                       json={"org_unit_id": tree["section"]["id"],
                             "items": [{"serial": "NVR001", "channels": [1, 2]}]}).json()
    cams = made[0]["cameras"]

    client.portal.call(cloud.sync_once)
    sent = bridge.accounts[acc["id"]]
    assert sent["session_id"].startswith("h.") and sent["auth_addr"] == "https://ieuauth.hik-connect.com"
    assert "password" not in json.dumps(bridge.accounts)
    assert bridge.want == []  # nobody watches: no cloud traffic

    # Someone opens the first camera's sub stream; face recognition reads the second's main.
    from app.services.streams import stream_name
    import uuid

    from app.models import StreamQuality

    cloud._watched[stream_name(uuid.UUID(cams[0]["id"]), StreamQuality.sub)] = time.time()
    body = {k: cams[1][k] for k in ("name", "org_unit_id", "direction", "schedule", "enabled", "rtsp_main",
                                     "rtsp_sub")}
    r = client.put(f"/api/cameras/{cams[1]['id']}", headers=admin,
                   json={**body, "face_recognition": True, "recognition_stream": "main"})
    assert r.status_code == 200, r.text
    client.portal.call(cloud.sync_once)
    assert {(w["serial"], w["channel"], w["sub"]) for w in bridge.want} == {("NVR001", 1, True), ("NVR001", 2, False)}
    assert all(w["account"] == acc["id"] for w in bridge.want)

    # The bridge reports a problem; the account list shows it.
    bridge.streams = {bridge.want[0]["target"]: {"state": "encrypted"}}
    client.portal.call(cloud.sync_once)
    info = client.get("/api/cloud", headers=admin).json()
    assert info["bridge"] is True
    assert info["accounts"][0]["problems"][0]["state"] == "encrypted"


def test_only_admins(client, admin, tree, cloud_fake):
    from tests.conftest import login

    r = client.post("/api/users", headers=admin, json={"username": "oper", "password": "secret123", "role": "operator",
                                                       "org_unit_id": tree["company"]["id"]})
    assert r.status_code == 201, r.text
    op = login(client, "oper", "secret123")
    assert client.get("/api/cloud", headers=op).status_code == 403
    assert client.post("/api/cloud/accounts", json=ACCOUNT, headers=op).status_code == 403

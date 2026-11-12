import pytest

from app.services.streams import Go2rtc
from tests.conftest import add_camera


@pytest.fixture
def cams(client, admin, tree):
    a = add_camera(client, admin, tree["branch_a"]["id"], name="A")
    b = add_camera(client, admin, tree["branch_b"]["id"], name="B", host="10.0.0.6")
    c = add_camera(client, admin, tree["section"]["id"], name="C", host="10.0.0.7")
    return a, b, c


def make_key(client, admin, cameras, name="Map"):
    r = client.post("/api/api-keys", json={"name": name, "camera_ids": [c["id"] for c in cameras]}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_key_is_shown_once_and_opens_only_its_cameras(client, admin, cams):
    a, b, c = cams
    made = make_key(client, admin, [a, c])
    secret = made["key"]
    assert secret.startswith("argus_") and made["prefix"] == secret[:10]

    # The list never carries the key again.
    listed = client.get("/api/api-keys", headers=admin).json()
    assert len(listed) == 1 and "key" not in listed[0] and listed[0]["last_used_at"] is None
    assert sorted(listed[0]["camera_ids"]) == sorted([a["id"], c["id"]])

    r = client.get("/api/ext/cameras", headers={"X-Api-Key": secret})
    assert r.status_code == 200, r.text
    got = r.json()
    assert [x["name"] for x in got] == ["A", "C"]
    assert got[1]["unit"] == "Acme / Tashkent / Plant 1 / Warehouse"
    assert got[0]["embed_path"] == f"/embed/{a['id']}"
    # Nothing about where the camera is or how to log into it.
    assert set(got[0]) == {"id", "name", "unit", "enabled", "online", "embed_path", "snapshot_path"}

    # The same key as a bearer token or in the address.
    assert client.get("/api/ext/cameras", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
    assert client.get("/api/ext/cameras", params={"key": secret}).status_code == 200
    assert client.get(f"/api/ext/cameras/{a['id']}", params={"key": secret}).json()["name"] == "A"
    assert client.get(f"/api/ext/cameras/{b['id']}", params={"key": secret}).status_code == 404
    assert client.get("/api/api-keys", headers=admin).json()[0]["last_used_at"] is not None


def test_wrong_or_missing_key_is_refused(client, admin, cams):
    a, _, _ = cams
    secret = make_key(client, admin, [a])["key"]
    for headers in ({}, {"X-Api-Key": "argus_nope"}, {"X-Api-Key": secret[:-1]}, admin):
        assert client.get("/api/ext/cameras", headers=headers).status_code == 401
    assert client.post(f"/api/ext/cameras/{a['id']}/webrtc", content="offer").status_code == 401
    # A key is not a login: it opens nothing of the site itself.
    assert client.get("/api/cameras", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_only_admin_manages_keys(client, admin, tree, cams):
    r = client.post("/api/users", json={"username": "oper", "password": "secret1", "role": "operator",
                                        "org_unit_id": tree["branch_a"]["id"]}, headers=admin)
    assert r.status_code == 201, r.text
    from tests.conftest import login

    op = login(client, "oper", "secret1")
    assert client.get("/api/api-keys", headers=op).status_code == 403
    assert client.post("/api/api-keys", json={"name": "x", "camera_ids": []}, headers=op).status_code == 403


def test_cameras_can_change_and_key_can_be_withdrawn(client, admin, cams):
    a, b, c = cams
    made = make_key(client, admin, [a])
    h = {"X-Api-Key": made["key"]}

    r = client.put(f"/api/api-keys/{made['id']}", json={"name": "Map 2", "camera_ids": [b["id"], c["id"]]},
                   headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "Map 2"
    assert [x["name"] for x in client.get("/api/ext/cameras", headers=h).json()] == ["B", "C"]

    r = client.put(f"/api/api-keys/{made['id']}",
                   json={"name": "Map 2", "camera_ids": ["00000000-0000-0000-0000-000000000000"]}, headers=admin)
    assert r.status_code == 422

    # A camera deleted from Argus drops out of the key.
    assert client.delete(f"/api/cameras/{c['id']}", headers=admin).status_code == 204
    assert [x["name"] for x in client.get("/api/ext/cameras", headers=h).json()] == ["B"]

    assert client.delete(f"/api/api-keys/{made['id']}", headers=admin).status_code == 204
    assert client.get("/api/ext/cameras", headers=h).status_code == 401
    assert client.get("/api/api-keys", headers=admin).json() == []


def test_video_and_snapshot_go_through_the_key(client, admin, cams, monkeypatch):
    a, b, _ = cams
    secret = make_key(client, admin, [a])["key"]
    asked = []

    async def webrtc(self, name, offer):
        asked.append(("webrtc", name, offer))
        return "answer-sdp"

    async def frame(self, name):
        asked.append(("frame", name))
        return b"\xff\xd8jpeg"

    monkeypatch.setattr(Go2rtc, "webrtc", webrtc)
    monkeypatch.setattr(Go2rtc, "frame", frame)

    r = client.post(f"/api/ext/cameras/{a['id']}/webrtc", content="offer-sdp", headers={"X-Api-Key": secret})
    assert r.status_code == 200 and r.text == "answer-sdp"
    assert r.headers["access-control-allow-origin"] == "*"
    r = client.get(f"/api/ext/cameras/{a['id']}/snapshot", params={"key": secret})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content.startswith(b"\xff\xd8")
    assert [x[0] for x in asked] == ["webrtc", "frame"] and asked[0][2] == "offer-sdp"

    assert client.post(f"/api/ext/cameras/{b['id']}/webrtc", content="o", headers={"X-Api-Key": secret}).status_code == 404
    assert client.get(f"/api/ext/cameras/{b['id']}/snapshot", params={"key": secret}).status_code == 404

    # Another site's page asks first whether it may call.
    r = client.options(f"/api/ext/cameras/{a['id']}/webrtc",
                       headers={"Origin": "https://map.example", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "*"
    # The rest of the API stays closed to other sites.
    assert "access-control-allow-origin" not in client.get("/api/health", headers={"Origin": "https://map.example"}).headers


def test_link_opens_one_camera_for_a_while(client, admin, cams, monkeypatch):
    a, b, _ = cams
    made = make_key(client, admin, [a, b])
    h = {"X-Api-Key": made["key"]}

    async def webrtc(self, name, offer):
        return "answer-sdp"

    monkeypatch.setattr(Go2rtc, "webrtc", webrtc)

    r = client.post(f"/api/ext/cameras/{a['id']}/link", headers=h)
    assert r.status_code == 200, r.text
    link = r.json()
    token = link["token"]
    assert link["embed_path"] == f"/embed/{a['id']}?t={token}" and made["key"] not in link["embed_path"]

    # The link plays its camera without the key, and only that camera.
    assert client.post(f"/api/ext/cameras/{a['id']}/webrtc", params={"t": token}, content="o").status_code == 200
    assert client.get(f"/api/ext/cameras/{a['id']}", params={"t": token}).json()["name"] == "A"
    assert client.post(f"/api/ext/cameras/{b['id']}/webrtc", params={"t": token}, content="o").status_code == 401
    assert client.get("/api/ext/cameras", params={"t": token}).status_code == 401
    assert client.post(f"/api/ext/cameras/{a['id']}/webrtc", params={"t": token + "0"}, content="o").status_code == 401

    # It dies with time...
    import app.api.ext as ext

    real = ext.time.time
    monkeypatch.setattr(ext.time, "time", lambda: real() + 3601)
    assert client.post(f"/api/ext/cameras/{a['id']}/webrtc", params={"t": token}, content="o").status_code == 401
    monkeypatch.setattr(ext.time, "time", real)

    # ...when the camera is taken out of the key, and when the key is withdrawn.
    client.put(f"/api/api-keys/{made['id']}", json={"name": "Map", "camera_ids": [b["id"]]}, headers=admin)
    assert client.post(f"/api/ext/cameras/{a['id']}/webrtc", params={"t": token}, content="o").status_code == 404
    token_b = client.post(f"/api/ext/cameras/{b['id']}/link", params={"seconds": 600}, headers=h).json()["token"]
    assert client.post(f"/api/ext/cameras/{b['id']}/webrtc", params={"t": token_b}, content="o").status_code == 200
    client.delete(f"/api/api-keys/{made['id']}", headers=admin)
    assert client.post(f"/api/ext/cameras/{b['id']}/webrtc", params={"t": token_b}, content="o").status_code == 401

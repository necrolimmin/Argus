import base64
import struct
from datetime import datetime, timezone

from app.models import StreamQuality
from app.services import recognizer
from app.services.streams import rtsp_url
from tests.conftest import add_camera, device_body, login

EMBEDDING = struct.pack("4f", 0.5, 0.5, 0.5, 0.5)


def test_login_and_me(client, admin):
    assert client.get("/api/auth/me", headers=admin).json()["role"] == "admin"
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    assert client.get("/api/cameras").status_code == 401


def test_hierarchy_levels_and_limits(client, admin, tree):
    levels = {u["name"]: u["level"] for u in client.get("/api/org-units", headers=admin).json()}
    assert levels == {
        "Acme": "company",
        "Tashkent": "branch",
        "Samarkand": "branch",
        "Plant 1": "enterprise",
        "Warehouse": "section",
        "Other Co": "company",
    }
    r = client.post(
        "/api/org-units", json={"name": "Too deep", "parent_id": tree["section"]["id"]}, headers=admin
    )
    assert r.status_code == 422


def test_camera_filter_covers_subtree(client, admin, tree):
    for name, unit in (("Gate", "section"), ("Lobby", "branch_a"), ("Yard", "branch_b")):
        r = client.post("/api/devices", json=device_body(tree[unit]["id"], name=name), headers=admin)
        assert r.status_code == 201, r.text
        assert "password" not in r.json() and r.json()["has_password"]

    def names(unit):
        r = client.get("/api/cameras", params={"org_unit_id": tree[unit]["id"]}, headers=admin)
        return sorted(c["name"] for c in r.json())

    assert names("company") == ["Gate", "Lobby", "Yard"]
    assert names("branch_a") == ["Gate", "Lobby"]
    assert names("enterprise") == ["Gate"]
    assert names("other") == []

    counts = {u["name"]: u["camera_count"] for u in client.get("/api/org-units", headers=admin).json()}
    assert counts["Acme"] == 3 and counts["Tashkent"] == 2 and counts["Warehouse"] == 1


def test_direction_cleared_without_face_recognition(client, admin, tree):
    cam = add_camera(client, admin, tree["branch_a"]["id"], face_recognition=False, direction="entry")
    assert cam["direction"] == "none"


def test_unit_with_cameras_cannot_be_deleted(client, admin, tree):
    add_camera(client, admin, tree["section"]["id"])
    assert client.delete(f"/api/org-units/{tree['branch_a']['id']}", headers=admin).status_code == 409
    # An empty branch goes away together with its empty children.
    assert client.delete(f"/api/org-units/{tree['branch_b']['id']}", headers=admin).status_code == 204


def test_operator_sees_only_own_subtree(client, admin, tree):
    add_camera(client, admin, tree["branch_a"]["id"], name="A")
    add_camera(client, admin, tree["branch_b"]["id"], name="B", host="10.0.0.6")
    r = client.post(
        "/api/users",
        json={"username": "operator1", "password": "secret1", "role": "operator", "org_unit_id": tree["branch_a"]["id"]},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    op = login(client, "operator1", "secret1")

    assert [c["name"] for c in client.get("/api/cameras", headers=op).json()] == ["A"]
    units = {u["name"] for u in client.get("/api/org-units", headers=op).json()}
    assert units == {"Tashkent", "Plant 1", "Warehouse"}
    r = client.get("/api/cameras", params={"org_unit_id": tree["branch_b"]["id"]}, headers=op)
    assert r.status_code == 404
    r = client.post("/api/devices", json=device_body(tree["branch_a"]["id"]), headers=op)
    assert r.status_code == 403
    assert client.get("/api/devices", headers=op).status_code == 403


def test_last_admin_cannot_be_demoted(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    r = client.patch(f"/api/users/{me['id']}", json={"is_active": False}, headers=admin)
    assert r.status_code == 409


def test_rtsp_templates():
    from app.models import Camera, CameraVendor, Device
    from app.security import encrypt_secret
    from app.services.streams import template_url

    dev = Device(vendor=CameraVendor.hikvision, host="10.0.0.5", rtsp_port=554,
                 username="admin", password_enc=encrypt_secret("p@ss:word"), credential=None)
    cam = Camera(channel=1, rtsp_main="", rtsp_sub="", device=dev)
    assert rtsp_url(cam, StreamQuality.sub) == "rtsp://admin:p%40ss%3Aword@10.0.0.5:554/Streaming/Channels/102"
    dev.vendor = CameraVendor.dahua
    assert rtsp_url(cam, StreamQuality.main).endswith("/cam/realmonitor?channel=1&subtype=0")
    cam.rtsp_main = "rtsp://10.0.0.9/live"
    assert rtsp_url(cam, StreamQuality.sub) == "rtsp://admin:p%40ss%3Aword@10.0.0.9/live"

    def t(vendor, ch=3, q=StreamQuality.main):
        return template_url(vendor, "h", 554, ch, q)

    assert t(CameraVendor.uniview) == "rtsp://h:554/unicast/c3/s0/live"
    assert t(CameraVendor.reolink, q=StreamQuality.sub) == "rtsp://h:554/h264Preview_03_sub"
    assert t(CameraVendor.vigi, q=StreamQuality.sub) == "rtsp://h:554/stream2"
    assert t(CameraVendor.axis) == "rtsp://h:554/axis-media/media.amp?camera=3"
    assert t(CameraVendor.dvrip) == "dvrip://h:34567?channel=2&subtype=0"
    assert t(CameraVendor.onvif) == ""


def _employee(client, admin, unit_id, name="Ivanov Ivan"):
    r = client.post(
        "/api/employees",
        json={"full_name": name, "personnel_number": "T-1", "position": "Driver", "org_unit_id": unit_id},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_photo_upload_feeds_gallery(client, admin, tree, monkeypatch):
    emp = _employee(client, admin, tree["section"]["id"])

    async def fake_embed(image, filename):
        return EMBEDDING

    monkeypatch.setattr("app.api.employees.embed_photo", fake_embed)
    r = client.post(
        f"/api/employees/{emp['id']}/photos", files={"file": ("a.jpg", b"jpeg")}, headers=admin
    )
    assert r.status_code == 200, r.text
    photo_url = r.json()["photos"][0]["url"]
    assert client.get(photo_url).content == b"jpeg"
    assert client.get(photo_url.replace("sig=", "sig=x")).status_code == 403

    svc = {"X-Service-Token": "svc"}
    gallery = client.get("/api/internal/recognizer/gallery", headers=svc).json()
    assert gallery["employees"] == [{"id": emp["id"], "embeddings": [base64.b64encode(EMBEDDING).decode()]}]
    assert client.get("/api/internal/recognizer/gallery").status_code == 401


def test_photo_rejected_when_face_check_fails(client, admin, tree, monkeypatch):
    emp = _employee(client, admin, tree["section"]["id"])

    async def no_face(image, filename):
        raise recognizer.FaceCheckError("face_not_found")

    monkeypatch.setattr("app.api.employees.embed_photo", no_face)
    r = client.post(f"/api/employees/{emp['id']}/photos", files={"file": ("a.jpg", b"x")}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"] == "face_not_found"


def test_events_flow_and_websocket(client, admin, tree):
    cam = add_camera(client, admin, tree["section"]["id"], face_recognition=True, direction="entry")
    emp = _employee(client, admin, tree["section"]["id"])
    svc = {"X-Service-Token": "svc"}

    config = client.get("/api/internal/recognizer/config", headers=svc).json()
    assert config["cameras"][0]["stream_url"].endswith(f"cam_{cam['id'].replace('-', '')}_sub")

    token = admin["Authorization"].split()[1]
    with client.websocket_connect(f"/api/ws/events?token={token}") as ws:
        ws.send_json({"type": "subscribe", "camera_ids": [cam["id"]]})
        assert ws.receive_json()["type"] == "subscribed"

        now = datetime.now(timezone.utc).isoformat()
        r = client.post(
            "/api/internal/events",
            data={"camera_id": cam["id"], "kind": "recognized", "occurred_at": now,
                  "employee_id": emp["id"], "similarity": "0.71"},
            files={"image": ("f.jpg", b"face")},
            headers=svc,
        )
        assert r.status_code == 201, r.text
        pushed = ws.receive_json()["event"]
        assert pushed["employee"]["full_name"] == "Ivanov Ivan"
        assert pushed["employee"]["org_unit"] == "Tashkent / Plant 1 / Warehouse"
        assert pushed["direction"] == "entry"

    r = client.post(
        "/api/internal/events",
        data={"camera_id": cam["id"], "kind": "unknown", "occurred_at": now,
              "embedding": base64.b64encode(EMBEDDING).decode()},
        files={"image": ("s.jpg", b"screen"), "face": ("c.jpg", b"crop")},
        headers=svc,
    )
    assert r.status_code == 201
    unknown = client.get(
        "/api/events", params={"camera_ids": [cam["id"]], "kind": "unknown"}, headers=admin
    ).json()
    assert len(unknown) == 1 and client.get(unknown[0]["image_url"]).content == b"screen"

    r = client.post(
        f"/api/events/{unknown[0]['id']}/employee",
        json={"full_name": "New Person", "org_unit_id": tree["section"]["id"]},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["photos"]) == 1
    again = client.get("/api/events", params={"kind": "unknown"}, headers=admin).json()
    assert again[0]["linked_employee_name"] == "New Person"

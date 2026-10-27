import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="argus-test-"))
_db = _tmp / "test.db"
os.environ.update(
    ARGUS_DATABASE_URL=f"sqlite+aiosqlite:///{_db.as_posix()}",
    ARGUS_MEDIA_DIR=str(_tmp / "media"),
    ARGUS_ADMIN_PASSWORD="secret-admin",
    ARGUS_SERVICE_TOKEN="svc",
    # Nothing listens here, so go2rtc calls fail fast and are logged.
    ARGUS_GO2RTC_URL="http://127.0.0.1:9",
    ARGUS_RECOGNIZER_URL="http://127.0.0.1:9",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def no_go2rtc(monkeypatch):
    """There is no go2rtc in tests; skip the registration round-trips."""

    async def nothing(*args, **kwargs):
        return None

    for target in ("app.api.devices", "app.api.cameras", "app.api.credentials"):
        for name in ("safe_register", "safe_unregister"):
            if hasattr(__import__(target, fromlist=[name]), name):
                monkeypatch.setattr(f"{target}.{name}", nothing)


@pytest.fixture
def client():
    engine = create_engine(f"sqlite:///{_db.as_posix()}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    with TestClient(create_app(background_jobs=False)) as c:
        yield c


def login(client, username="admin", password="secret-admin") -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client)


@pytest.fixture
def tree(client, admin):
    """Two companies; the first has a full four-level chain."""

    def unit(name, parent=None):
        r = client.post("/api/org-units", json={"name": name, "parent_id": parent}, headers=admin)
        assert r.status_code == 201, r.text
        return r.json()

    company = unit("Acme")
    branch_a = unit("Tashkent", company["id"])
    branch_b = unit("Samarkand", company["id"])
    enterprise = unit("Plant 1", branch_a["id"])
    section = unit("Warehouse", enterprise["id"])
    other = unit("Other Co")
    return dict(
        company=company,
        branch_a=branch_a,
        branch_b=branch_b,
        enterprise=enterprise,
        section=section,
        other=other,
    )


def device_body(org_unit_id, name="Gate", host="10.0.0.5", channels=None, **kw):
    body = dict(
        name=name,
        vendor="hikvision",
        host=host,
        username="admin",
        password="p@ss:word",
        org_unit_id=org_unit_id,
        channels=channels or [{"channel": 1, "name": name}],
    )
    body.update(kw)
    return body


def add_camera(client, headers, org_unit_id, name="Gate", host="10.0.0.5", **settings):
    """Adds a one-channel device and applies channel settings; returns the camera."""
    r = client.post("/api/devices", json=device_body(org_unit_id, name, host), headers=headers)
    assert r.status_code == 201, r.text
    cam = r.json()["cameras"][0]
    if settings:
        body = {k: cam[k] for k in ("name", "org_unit_id", "face_recognition", "direction", "schedule",
                                    "recognition_stream", "enabled", "rtsp_main", "rtsp_sub")}
        body.update(settings)
        r = client.put(f"/api/cameras/{cam['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        cam = r.json()
    return cam

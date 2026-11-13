import pytest

from app.config import get_settings
from app.services import login_guard

GOOD = {"username": "admin", "password": "secret-admin"}


@pytest.fixture(autouse=True)
def clean():
    login_guard.reset()
    yield
    login_guard.reset()


@pytest.fixture
def with_captcha(monkeypatch):
    monkeypatch.setattr(get_settings(), "captcha_enabled", True)


def solve(client) -> dict:
    """Ask for a picture and read its answer where the server keeps it."""
    c = client.get("/api/auth/captcha").json()
    assert c["enabled"] and c["image"].startswith("<svg")
    answer, _ = login_guard._captchas[c["id"]]
    # The digits are drawn as lines: the answer is not in the picture's text.
    assert answer not in c["image"]
    return {"captcha_id": c["id"], "captcha_answer": answer}


def test_captcha_off_says_so(client):
    assert client.get("/api/auth/captcha").json() == {"enabled": False, "id": "", "image": ""}


def test_login_needs_the_digits(client, with_captcha):
    r = client.post("/api/auth/login", json=GOOD)
    assert r.status_code == 400 and r.json()["detail"] == "captcha_wrong"

    r = client.post("/api/auth/login", json={**GOOD, **solve(client)})
    assert r.status_code == 200


def test_wrong_digits_and_reuse(client, with_captcha):
    solved = solve(client)
    wrong = {**solved, "captcha_answer": "x"}
    assert client.post("/api/auth/login", json={**GOOD, **wrong}).json()["detail"] == "captcha_wrong"
    # A picture is good for one try: after a wrong answer the right one no longer works.
    assert client.post("/api/auth/login", json={**GOOD, **solved}).json()["detail"] == "captcha_wrong"

    solved = solve(client)
    assert client.post("/api/auth/login", json={**GOOD, **solved}).status_code == 200
    assert client.post("/api/auth/login", json={**GOOD, **solved}).json()["detail"] == "captcha_wrong"


def test_pause_after_too_many_wrong_passwords(client):
    bad = {"username": "admin", "password": "nope"}
    for _ in range(get_settings().login_max_failures):
        assert client.post("/api/auth/login", json=bad).status_code == 401

    r = client.post("/api/auth/login", json=GOOD)
    assert r.status_code == 429 and r.json()["detail"] == "too_many_attempts"
    assert 0 < int(r.headers["retry-after"]) <= get_settings().login_lock_minutes * 60

    # The pause is for this login from this address; another login is not held up.
    assert client.post("/api/auth/login", json={"username": "someone", "password": "x"}).status_code == 401


def test_success_clears_the_count(client):
    bad = {"username": "admin", "password": "nope"}
    for _ in range(get_settings().login_max_failures - 1):
        client.post("/api/auth/login", json=bad)
    assert client.post("/api/auth/login", json=GOOD).status_code == 200
    for _ in range(get_settings().login_max_failures - 1):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    assert client.post("/api/auth/login", json=GOOD).status_code == 200

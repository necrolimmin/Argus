"""Cameras from Hik-Connect / EZVIZ accounts.

The admin logs Argus into an account and picks which of its cameras (or
recorder channels) to show. Video comes from the vendor's cloud, so nothing
has to be set up on the camera's side or on the router.

Every few seconds this module:

- keeps each account's cloud session alive (refreshes it; logs in again with
  the stored password only when the cloud has ended it, and not more than
  once in LOGIN_RETRY seconds, so a wrong password never locks the account);
- every DEVICE_LIST_SECONDS reads the account's device list and marks
  Argus devices online or offline;
- gives the cloud-bridge service the sessions and the list of streams to
  keep open. Cloud streams cost the owner's upload and the cloud's patience,
  so a stream is open only while someone watches it (and a minute after),
  or while face recognition reads it.

The bridge pushes each stream into go2rtc under the camera's usual stream
name, like the ISUP bridge does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Camera, CameraVendor, CloudAccount, Device, StreamQuality
from app.security import decrypt_secret, encrypt_secret
from app.services import cloud_api
from app.services.cloud_api import CloudError, Session
from app.services.streams import has_video, live_streams, stream_name

log = logging.getLogger(__name__)

REFRESH_AFTER = 45 * 60  # sessions last longer; refresh well before
LOGIN_RETRY = 15 * 60
DEVICE_LIST_SECONDS = 120

_sessions: dict[uuid.UUID, Session] = {}
_login_failed_at: dict[uuid.UUID, float] = {}
_listed_at: dict[uuid.UUID, float] = {}
_state: dict = {}
_state_at = 0.0
_watched: dict[str, float] = {}
_last_accounts = ""
_last_want = ""
_last_want_at = 0.0
_kick = asyncio.Event()


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(base_url=s.cloud_bridge_url, timeout=5, headers={"X-Bridge-Token": s.service_token})


def state() -> dict:
    """The bridge's last report, or {} when it is not running."""
    return _state if time.monotonic() - _state_at < 30 else {}


def stream_state(cam: Camera) -> dict:
    """What the bridge says about this camera's streams: {quality: {state, error}}."""
    streams = state().get("streams") or {}
    return {q.value: streams[n] for q in StreamQuality if (n := stream_name(cam.id, q)) in streams}


# --- sessions --------------------------------------------------------------------


def _save(acc: CloudAccount, s: Session | None) -> None:
    if s is None:
        _sessions.pop(acc.id, None)
        acc.session_enc = ""
        return
    _sessions[acc.id] = s
    acc.session_enc = encrypt_secret(json.dumps(s.to_dict()))
    acc.api_domain = s.api


def _stored(acc: CloudAccount) -> Session | None:
    if acc.id in _sessions:
        return _sessions[acc.id]
    if not acc.session_enc:
        return None
    try:
        s = Session.from_dict(json.loads(decrypt_secret(acc.session_enc)))
    except (ValueError, TypeError):
        return None
    _sessions[acc.id] = s
    return s


async def log_in(acc: CloudAccount, password: str | None = None, sms_code: str = "") -> Session:
    """Logs in with the given or stored password; stores the session on success."""
    pw = password if password is not None else decrypt_secret(acc.password_enc)
    try:
        s = await cloud_api.login(acc.provider, acc.login, pw, acc.feature_code, acc.api_domain if password is None else "",
                                  sms_code)
    except CloudError as exc:
        acc.error = exc.code
        _login_failed_at[acc.id] = time.monotonic()
        raise
    _login_failed_at.pop(acc.id, None)
    _save(acc, s)
    acc.error = ""
    return s


async def session(acc: CloudAccount, force_login: bool = False) -> Session:
    """A live session for the account, refreshing or logging in as needed.

    Raises CloudError when there is none to be had right now.
    """
    s = None if force_login else _stored(acc)
    if s is not None and time.time() - s.at > REFRESH_AFTER:
        try:
            s = await cloud_api.refresh(s)
            _save(acc, s)
        except CloudError as exc:
            if exc.code == "cloud_unavailable":
                return s  # try again later; the old session may still work
            s = None
    if s is not None:
        return s
    failed = _login_failed_at.get(acc.id)
    if failed is not None and time.monotonic() - failed < LOGIN_RETRY:
        raise CloudError(acc.error or "cloud_session")
    return await log_in(acc)


async def devices(acc: CloudAccount) -> list[dict]:
    """The account's devices; logs in again once if the session has ended."""
    s = await session(acc)
    try:
        found = await cloud_api.devices(s)
    except CloudError as exc:
        if exc.code != "cloud_session":
            acc.error = exc.code
            raise
        _save(acc, None)
        found = await cloud_api.devices(await session(acc, force_login=True))
    acc.error = ""
    acc.checked_at = datetime.now(timezone.utc)
    _listed_at[acc.id] = time.monotonic()
    return found


def forget(account_id: uuid.UUID) -> None:
    for d in (_sessions, _login_failed_at, _listed_at):
        d.pop(account_id, None)


# --- the bridge ------------------------------------------------------------------


def want_list(cameras: list[Camera], now: float, watched: dict[str, float], live: set[str]) -> list[dict]:
    """Streams the bridge should keep open: one per camera, its sub stream.

    The main stream is never pulled from the cloud (see streams.playable_quality).
    """
    idle = get_settings().cloud_idle_seconds
    out = []
    for cam in cameras:
        dev = cam.device
        if not cam.enabled or dev.cloud_account_id is None or not dev.serial:
            continue
        names = [stream_name(cam.id, q) for q in StreamQuality]
        needed = cam.face_recognition or any(now - watched.get(n, 0) < idle or n in live for n in names)
        if needed:
            out.append({"target": stream_name(cam.id, StreamQuality.sub), "account": str(dev.cloud_account_id),
                        "serial": dev.serial, "channel": cam.channel, "sub": True})
    return sorted(out, key=lambda w: w["target"])


async def _refresh_devices(session_db, acc: CloudAccount, devs: list[Device]) -> None:
    try:
        found = {d["serial"]: d for d in await devices(acc)}
    except CloudError as exc:
        log.warning("cloud account %s: %s", acc.login, exc)
        return
    now = datetime.now(timezone.utc)
    for dev in devs:
        if dev.cloud_account_id != acc.id:
            continue
        info = found.get(dev.serial)
        dev.online = bool(info and info["online"])
        if info is None:
            continue
        if dev.online:
            dev.last_seen_at = now
        dev.model = info["model"] or dev.model
        listed = {c["channel"] for c in info["channels"]}
        for cam in dev.cameras:
            cam.missing = cam.channel not in listed


async def sync_once() -> None:
    global _state, _state_at, _last_accounts, _last_want, _last_want_at
    async with SessionLocal() as db:
        accounts = (await db.scalars(select(CloudAccount))).all()
        if not accounts:
            return
        devs = (await db.scalars(select(Device).where(Device.vendor == CameraVendor.cloud))).unique().all()

        # Sessions the bridge reported as ended are renewed first.
        ended = set(state().get("expired") or [])
        sessions = {}
        for acc in accounts:
            try:
                sessions[str(acc.id)] = await session(acc, force_login=str(acc.id) in ended)
            except CloudError as exc:
                log.debug("cloud account %s: %s", acc.login, exc)
            if time.monotonic() - _listed_at.get(acc.id, 0) > DEVICE_LIST_SECONDS:
                _listed_at[acc.id] = time.monotonic()
                await _refresh_devices(db, acc, devs)
        await db.commit()
        cameras = [cam for dev in devs for cam in dev.cameras]

    async with _client() as c:
        try:
            r = await c.get("/state")
            r.raise_for_status()
            _state, _state_at = r.json(), time.monotonic()
        except Exception as exc:  # noqa: BLE001
            log.debug("cloud bridge not reachable: %s", exc)
            return

        body = json.dumps({k: {"provider": s.provider, "api": s.api, "session_id": s.session_id,
                               "feature_code": s.feature_code, "auth_addr": s.auth_addr}
                           for k, s in sorted(sessions.items())})
        if body != _last_accounts or not _state.get("accounts_set") or ended:
            await c.put("/accounts", content=body)
            _last_accounts = body

        t = time.time()
        for name, at in list(_watched.items()):
            if t - at > 3600:
                del _watched[name]
        want = json.dumps(want_list(cameras, t, _watched, await live_streams()))
        if want != _last_want or t - _last_want_at > 30:
            await c.put("/want", content=want)
            _last_want, _last_want_at = want, t


async def run() -> None:
    while True:
        try:
            await sync_once()
        except Exception:  # noqa: BLE001
            log.exception("cloud sync failed")
        _kick.clear()
        try:
            await asyncio.wait_for(_kick.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


async def touch(cam: Camera, quality: StreamQuality, wait: float = 15) -> None:
    """Someone is about to watch: ask the bridge to open the stream and wait for video.

    Opening a cloud stream takes a few seconds (ticket, relay, first frame).
    """
    name = stream_name(cam.id, quality)
    _watched[name] = time.time()
    if await has_video(name):
        return
    _kick.set()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        await asyncio.sleep(0.4)
        if await has_video(name):
            return
        st = (state().get("streams") or {}).get(name) or {}
        if st.get("state") in ("encrypted", "offline", "failed"):
            return  # it will not come; the page shows why

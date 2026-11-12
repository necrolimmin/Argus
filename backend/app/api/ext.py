"""What another system can ask Argus for with an API key.

The key opens the cameras ticked for it: their list, a still picture and
live video. Addresses, logins and passwords of the cameras never leave Argus;
the other system gets video through Argus only.

The key goes in the `X-Api-Key` header (or `Authorization: Bearer`, or
`?key=` where a header cannot be set, e.g. an <iframe>).

A page shown to many people should not carry the key itself. For that the
other system's server asks for a link (`POST .../link`): it holds a token
that opens one camera for a limited time.
"""

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, WebSocket, status
from sqlalchemy import select

from app.api.cameras import answer_offer, open_stream, relay_mse
from app.config import get_settings
from app.db import SessionLocal
from app.deps import Session
from app.models import ApiKey, Camera, OrgUnit, StreamQuality
from app.schemas import ExtCamera, ExtLink
from app.services.streams import Go2rtcError, go2rtc

router = APIRouter(prefix="/ext", tags=["external"])

KEY_PREFIX = "argus_"
LINK_SECONDS = 60 * 60
LINK_MAX_SECONDS = 7 * 24 * 60 * 60
# "Last used" is for the administrator's eye; once a minute is exact enough.
USED_EVERY = timedelta(minutes=1)


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    # The key is 256 random bits, so a plain hash is enough: there is nothing to guess.
    return hashlib.sha256(key.encode()).hexdigest()


# --- links: one camera, for a while ------------------------------------------------


def _link_sig(key_id: uuid.UUID, camera_id: uuid.UUID, exp: int) -> str:
    msg = f"ext:{key_id.hex}:{camera_id.hex}:{exp}".encode()
    return hmac.new(get_settings().secret_key.encode(), msg, hashlib.sha256).hexdigest()[:40]


def link_token(key_id: uuid.UUID, camera_id: uuid.UUID, seconds: int) -> tuple[str, int]:
    exp = int(time.time()) + seconds
    return f"{key_id.hex}.{exp}.{_link_sig(key_id, camera_id, exp)}", exp


def read_link_token(token: str, camera_id: uuid.UUID) -> uuid.UUID | None:
    """The id of the key a link was made with, if the link is genuine and still good."""
    try:
        key_hex, exp_text, sig = token.split(".")
        key_id, exp = uuid.UUID(hex=key_hex), int(exp_text)
    except ValueError:
        return None
    if exp < time.time() or not hmac.compare_digest(_link_sig(key_id, camera_id, exp), sig):
        return None
    return key_id


# --- who is asking -------------------------------------------------------------------


def _given(x_api_key: str | None, authorization: str | None, key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    bearer = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    # A browser signed in to Argus sends its own login here; that is not a key.
    if bearer.startswith(KEY_PREFIX):
        return bearer
    return (key or "").strip()


async def _find_key(session, secret: str) -> ApiKey | None:
    if not secret.startswith(KEY_PREFIX):
        return None
    return await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(secret)))


async def _mark_used(session, key: ApiKey) -> None:
    now = datetime.now(timezone.utc)
    last = key.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last > USED_EVERY:
        key.last_used_at = now
        await session.commit()


async def holder(
    session: Session,
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    key: Annotated[str | None, Query()] = None,
) -> ApiKey:
    """The key the request came with."""
    found = await _find_key(session, _given(x_api_key, authorization, key))
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad_api_key")
    await _mark_used(session, found)
    return found


Holder = Annotated[ApiKey, Depends(holder)]


async def _camera_for(session, secret: str, token: str, camera_id: uuid.UUID) -> Camera:
    """The camera, if the key or the link opens it; otherwise 401 or 404."""
    key = None
    if secret:
        key = await _find_key(session, secret)
    elif token:
        key_id = read_link_token(token, camera_id)
        # A link stops working when its key is withdrawn or loses the camera.
        key = await session.get(ApiKey, key_id) if key_id else None
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad_api_key")
    cam = await session.get(Camera, camera_id) if camera_id in key.camera_ids else None
    if cam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera_not_found")
    await _mark_used(session, key)
    return cam


async def watched(
    camera_id: uuid.UUID,
    session: Session,
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    key: Annotated[str | None, Query()] = None,
    t: Annotated[str | None, Query()] = None,
) -> Camera:
    return await _camera_for(session, _given(x_api_key, authorization, key), t or "", camera_id)


Watched = Annotated[Camera, Depends(watched)]


# --- answers -------------------------------------------------------------------------


async def _unit_names(session, cameras: list[Camera]) -> dict[uuid.UUID, str]:
    """ "Company / Branch / Section" for each camera's unit."""
    ids = {uuid.UUID(hex=part) for cam in cameras for part in cam.org_unit.path.strip("/").split("/") if part}
    names = {}
    if ids:
        rows = await session.execute(select(OrgUnit.id, OrgUnit.name).where(OrgUnit.id.in_(ids)))
        names = {row.id.hex: row.name for row in rows}
    return {
        cam.id: " / ".join(names.get(part, "") for part in cam.org_unit.path.strip("/").split("/") if part)
        for cam in cameras
    }


def _out(cam: Camera, unit: str) -> ExtCamera:
    return ExtCamera(
        id=cam.id,
        name=cam.name,
        unit=unit,
        enabled=cam.enabled,
        online=cam.device.online,
        embed_path=f"/embed/{cam.id}",
        snapshot_path=f"/api/ext/cameras/{cam.id}/snapshot",
    )


@router.get("/cameras", response_model=list[ExtCamera])
async def cameras(key: Holder, session: Session):
    """The cameras this key opens."""
    ids = key.camera_ids
    if not ids:
        return []
    found = (await session.scalars(select(Camera).where(Camera.id.in_(ids)).order_by(Camera.name))).unique().all()
    units = await _unit_names(session, found)
    return [_out(cam, units[cam.id]) for cam in found]


@router.get("/cameras/{camera_id}", response_model=ExtCamera)
async def camera(cam: Watched, session: Session):
    return _out(cam, (await _unit_names(session, [cam]))[cam.id])


@router.post("/cameras/{camera_id}/link", response_model=ExtLink)
async def link(
    camera_id: uuid.UUID,
    key: Holder,
    seconds: Annotated[int, Query(ge=60, le=LINK_MAX_SECONDS)] = LINK_SECONDS,
):
    """A link to the camera's player that works for a while and does not carry the key."""
    if camera_id not in key.camera_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera_not_found")
    token, exp = link_token(key.id, camera_id, seconds)
    return ExtLink(token=token, embed_path=f"/embed/{camera_id}?t={token}",
                   expires_at=datetime.fromtimestamp(exp, timezone.utc))


@router.get("/cameras/{camera_id}/snapshot")
async def snapshot(cam: Watched, quality: StreamQuality = StreamQuality.sub):
    """The camera's picture right now, as a JPEG."""
    if not cam.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "camera_disabled")
    name = await open_stream(cam, quality)
    try:
        try:
            image = await go2rtc().frame(name)
        except LookupError:
            await go2rtc().register(cam)
            image = await go2rtc().frame(name)
    except (LookupError, Go2rtcError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "stream_unavailable") from exc
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/cameras/{camera_id}/webrtc", response_class=Response)
async def webrtc(cam: Watched, request: Request, quality: StreamQuality = StreamQuality.sub):
    """Live video: send the browser's SDP offer, get go2rtc's answer."""
    offer = (await request.body()).decode()
    return Response(await answer_offer(cam, quality, offer), media_type="application/sdp")


@router.websocket("/cameras/{camera_id}/mse")
async def mse(
    ws: WebSocket,
    camera_id: uuid.UUID,
    key: str = "",
    t: str = "",
    quality: StreamQuality = StreamQuality.sub,
):
    """Live video as fragmented MP4 over a WebSocket, for cameras that send H.265."""
    try:
        async with SessionLocal() as session:
            cam = await _camera_for(session, key.strip(), t, camera_id)
            _ = cam.device.vendor  # loaded while the session is open
    except HTTPException:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not cam.enabled:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await relay_mse(ws, cam, quality)


# --- other sites may call these from a browser ---------------------------------------

_CORS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-headers", b"X-Api-Key, Authorization, Content-Type"),
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-max-age", b"86400"),
]


class OpenCors:
    """Lets pages of other sites call /api/ext/. It is safe to open to any site:
    nothing here trusts cookies, every request must carry a key or a link."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/ext/"):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": _CORS})
            await send({"type": "http.response.body", "body": b""})
            return

        async def with_cors(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *_CORS]}
            await send(message)

        await self.app(scope, receive, with_cors)

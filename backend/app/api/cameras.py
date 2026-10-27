import asyncio
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, status
from sqlalchemy import select
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

from app.db import SessionLocal
from app.deps import AdminUser, CurrentUser, Session, in_scope, scope_path, user_from_token
from app.models import Camera, OrgUnit, StreamQuality
from app.schemas import CameraOut, CameraUpdate
from app.services.org import get_unit_in_scope
from app.services.streams import Go2rtcError, go2rtc, safe_register, safe_unregister, stream_name

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _out(cam: Camera) -> CameraOut:
    return CameraOut.model_validate(cam)


async def _camera_in_scope(session, user, camera_id: uuid.UUID) -> Camera:
    cam = await session.get(Camera, camera_id)
    if cam is None or not in_scope(user, cam.org_unit.path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera_not_found")
    return cam


@router.get("", response_model=list[CameraOut])
async def list_cameras(
    user: CurrentUser,
    session: Session,
    org_unit_id: uuid.UUID | None = None,
    face_recognition: bool | None = None,
):
    """Cameras attached to the unit or anywhere below it."""
    query = select(Camera).join(Camera.org_unit).order_by(Camera.name)
    prefix = scope_path(user)
    if prefix is not None:
        query = query.where(OrgUnit.path.startswith(prefix))
    if org_unit_id is not None:
        unit = await get_unit_in_scope(session, user, org_unit_id)
        query = query.where(OrgUnit.path.startswith(unit.path))
    if face_recognition is not None:
        query = query.where(Camera.face_recognition == face_recognition)
    return [_out(c) for c in (await session.scalars(query)).unique().all()]


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: uuid.UUID, user: CurrentUser, session: Session):
    return _out(await _camera_in_scope(session, user, camera_id))


@router.put("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: uuid.UUID, body: CameraUpdate, user: AdminUser, session: Session):
    """Channel settings. Address and credentials are changed on the device."""
    cam = await _camera_in_scope(session, user, camera_id)
    await get_unit_in_scope(session, user, body.org_unit_id)
    streams_changed = (cam.rtsp_main, cam.rtsp_sub, cam.enabled) != (body.rtsp_main, body.rtsp_sub, body.enabled)
    data = body.model_dump(exclude={"schedule"})
    for key, value in data.items():
        setattr(cam, key, value)
    cam.schedule = [w.model_dump() for w in body.schedule]
    await session.commit()
    cam = await session.get(Camera, cam.id, populate_existing=True)
    if streams_changed:
        await safe_register(cam)
    return _out(cam)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: uuid.UUID, user: AdminUser, session: Session):
    """Removes one channel; a single-camera device goes with its last camera."""
    cam = await _camera_in_scope(session, user, camera_id)
    device = cam.device
    await session.delete(cam)
    await session.flush()
    await session.refresh(device)
    if not device.cameras:
        await session.delete(device)
    await session.commit()
    await safe_unregister(camera_id)


@router.post("/{camera_id}/webrtc", response_class=Response)
async def webrtc(
    camera_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    request: Request,
    quality: StreamQuality = StreamQuality.sub,
):
    """Exchanges the browser's SDP offer with go2rtc.

    Only the handshake passes through the backend; the video itself flows
    straight from go2rtc to the browser.
    """
    offer = (await request.body()).decode()
    cam = await _camera_in_scope(session, user, camera_id)
    if not cam.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "camera_disabled")
    name = stream_name(cam.id, quality)
    try:
        try:
            answer = await go2rtc().webrtc(name, offer)
        except LookupError:
            await go2rtc().register(cam)
            answer = await go2rtc().webrtc(name, offer)
    except (LookupError, Go2rtcError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "stream_unavailable") from exc
    return Response(answer, media_type="application/sdp")


@router.websocket("/{camera_id}/mse")
async def mse(ws: WebSocket, camera_id: uuid.UUID, token: str = "", quality: StreamQuality = StreamQuality.sub):
    """Relays go2rtc's MSE stream (fragmented MP4 over WebSocket).

    Used when WebRTC cannot carry the camera's codec: browsers play H.265
    through MSE with hardware decoding, so cameras left on H.265 still work
    without re-encoding on the server.
    """
    async with SessionLocal() as session:
        user = await user_from_token(session, token)
        cam = await session.get(Camera, camera_id)
        allowed = user is not None and cam is not None and cam.enabled and in_scope(user, cam.org_unit.path)
    if not allowed:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    name = stream_name(cam.id, quality)
    try:
        await go2rtc().ensure(cam, name)
        async with ws_connect(go2rtc().ws_url(name), max_size=None) as upstream:

            async def to_go2rtc():
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("text") is not None:
                        await upstream.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await upstream.send(msg["bytes"])

            async def to_browser():
                async for msg in upstream:
                    if isinstance(msg, str):
                        await ws.send_text(msg)
                    else:
                        await ws.send_bytes(msg)

            tasks = [asyncio.create_task(to_go2rtc()), asyncio.create_task(to_browser())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except (OSError, httpx.HTTPError, WebSocketException) as exc:
        log.info("mse relay for %s ended: %s", camera_id, exc)
    except Exception as exc:  # noqa: BLE001  (client went away mid-send)
        log.debug("mse relay for %s closed: %s", camera_id, exc)
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass

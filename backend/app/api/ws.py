import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.db import SessionLocal
from app.deps import scope_path, user_from_token
from app.models import Camera, OrgUnit
from app.services.hub import Client, hub

router = APIRouter()


@router.websocket("/ws/events")
async def events_socket(ws: WebSocket, token: str = ""):
    """Live face events.

    The client sends {"type": "subscribe", "camera_ids": [...]} whenever its
    selection changes and receives {"type": "event", "event": {...}}.
    """
    async with SessionLocal() as session:
        user = await user_from_token(session, token)
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    client = Client(ws=ws, user=user)
    hub.add(client)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "subscribe":
                continue
            ids = []
            for raw in msg.get("camera_ids", [])[:500]:
                try:
                    ids.append(uuid.UUID(str(raw)))
                except ValueError:
                    pass
            client.cameras = await _allowed(user, ids)
            await ws.send_json({"type": "subscribed", "camera_ids": [str(i) for i in client.cameras]})
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        hub.remove(client)


async def _allowed(user, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    query = select(Camera.id).join(Camera.org_unit).where(Camera.id.in_(ids))
    prefix = scope_path(user)
    if prefix is not None:
        query = query.where(OrgUnit.path.startswith(prefix))
    async with SessionLocal() as session:
        return set((await session.scalars(query)).all())

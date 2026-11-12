"""Keys for other systems, made and withdrawn by an administrator.

A key opens the picture of the cameras ticked for it and nothing else; see
app/api/ext.py for what its holder can ask for.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.ext import hash_key, new_key
from app.deps import AdminUser, Session
from app.models import ApiKey, ApiKeyCamera, Camera
from app.schemas import ApiKeyCreated, ApiKeyIn, ApiKeyOut

router = APIRouter(prefix="/api-keys", tags=["api keys"])

# How much of a key is kept readable, to tell keys apart in the list.
PREFIX_LENGTH = 10


async def _set_cameras(session, key: ApiKey, camera_ids: list[uuid.UUID]) -> None:
    wanted = list(dict.fromkeys(camera_ids))
    if wanted:
        found = set((await session.scalars(select(Camera.id).where(Camera.id.in_(wanted)))).all())
        if len(found) != len(wanted):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "camera_not_found")
    keep = set(wanted)
    links = [link for link in key.camera_links if link.camera_id in keep]
    have = {link.camera_id for link in links}
    key.camera_links = links + [ApiKeyCamera(camera_id=cid) for cid in wanted if cid not in have]


async def _get(session, key_id: uuid.UUID) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "api_key_not_found")
    return key


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(user: AdminUser, session: Session):
    return (await session.scalars(select(ApiKey).order_by(ApiKey.created_at))).all()


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(body: ApiKeyIn, user: AdminUser, session: Session):
    """Makes a key. The key itself is in this answer only: Argus keeps its hash."""
    secret = new_key()
    key = ApiKey(name=body.name.strip(), prefix=secret[:PREFIX_LENGTH], key_hash=hash_key(secret), camera_links=[])
    session.add(key)
    await _set_cameras(session, key, body.camera_ids)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreated.model_validate(key).model_copy(update={"key": secret})


@router.put("/{key_id}", response_model=ApiKeyOut)
async def update_key(key_id: uuid.UUID, body: ApiKeyIn, user: AdminUser, session: Session):
    """Renames the key or changes its cameras; the key itself stays the same."""
    key = await _get(session, key_id)
    key.name = body.name.strip()
    await _set_cameras(session, key, body.camera_ids)
    await session.commit()
    await session.refresh(key)
    return key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(key_id: uuid.UUID, user: AdminUser, session: Session):
    """Withdraws the key: whoever holds it loses the cameras at once."""
    await session.delete(await _get(session, key_id))
    await session.commit()

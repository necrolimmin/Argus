import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, Session
from app.models import CredentialProfile, Device
from app.schemas import CredentialIn, CredentialOut
from app.security import encrypt_secret
from app.services.streams import safe_register

router = APIRouter(prefix="/credentials", tags=["credentials"])


async def _counts(session) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Device.credential_id, func.count()).where(Device.credential_id.is_not(None)).group_by(Device.credential_id)
    )
    return dict(rows.all())


@router.get("", response_model=list[CredentialOut])
async def list_profiles(_: AdminUser, session: Session):
    counts = await _counts(session)
    profiles = (await session.scalars(select(CredentialProfile).order_by(CredentialProfile.name))).all()
    return [
        CredentialOut(id=p.id, name=p.name, username=p.username, device_count=counts.get(p.id, 0))
        for p in profiles
    ]


async def _commit(session) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "credential_name_taken") from exc


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_profile(body: CredentialIn, _: AdminUser, session: Session):
    profile = CredentialProfile(
        name=body.name.strip(), username=body.username, password_enc=encrypt_secret(body.password)
    )
    session.add(profile)
    await _commit(session)
    return CredentialOut(id=profile.id, name=profile.name, username=profile.username)


@router.put("/{profile_id}", response_model=CredentialOut)
async def update_profile(profile_id: uuid.UUID, body: CredentialIn, _: AdminUser, session: Session):
    profile = await session.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential_not_found")
    profile.name, profile.username = body.name.strip(), body.username
    if body.password:
        profile.password_enc = encrypt_secret(body.password)
    await _commit(session)

    # Every device using the profile gets the new login in go2rtc.
    devices = (await session.scalars(select(Device).where(Device.credential_id == profile_id))).unique().all()
    for dev in devices:
        await session.refresh(dev)
        for cam in dev.cameras:
            await safe_register(cam)
    counts = await _counts(session)
    return CredentialOut(id=profile.id, name=profile.name, username=profile.username, device_count=counts.get(profile.id, 0))


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: uuid.UUID, _: AdminUser, session: Session):
    profile = await session.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential_not_found")
    if (await _counts(session)).get(profile_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "credential_in_use")
    await session.delete(profile)
    await session.commit()

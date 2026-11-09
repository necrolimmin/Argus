"""Hik-Connect / EZVIZ accounts: log in, list the account's cameras, add them."""

import hashlib
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import AdminUser, Session
from app.models import Camera, CameraVendor, CloudAccount, Device, DeviceKind
from app.schemas import (
    CloudAccountIn,
    CloudAccountOut,
    CloudAccountUpdate,
    CloudAddIn,
    CloudChannel,
    CloudDevice,
    CloudInfo,
    CloudProblem,
    DeviceOut,
)
from app.security import encrypt_secret
from app.services import cloud
from app.services.cloud_api import CloudError
from app.services.org import get_unit_in_scope
from app.services.streams import safe_register, safe_unregister

router = APIRouter(prefix="/cloud", tags=["cloud"])

# Stream states worth showing the admin: the camera will not play until fixed.
PROBLEMS = ("encrypted", "offline", "failed")


def _feature_code(provider: str, login: str) -> str:
    # The same "phone" for this Argus and this account on every login, which
    # also keeps a two-step login code valid between the two attempts.
    seed = f"{get_settings().secret_key}:{provider}:{login.strip().lower()}"
    return hashlib.md5(seed.encode()).hexdigest()


def _fail(exc: CloudError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if exc.code == "cloud_needs_code" else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, exc.code)


async def _account(session, account_id: uuid.UUID) -> CloudAccount:
    acc = await session.get(CloudAccount, account_id)
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cloud_account_not_found")
    return acc


async def _out(session, acc: CloudAccount) -> CloudAccountOut:
    devs = (await session.scalars(select(Device).where(Device.cloud_account_id == acc.id))).unique().all()
    problems = []
    for dev in devs:
        for cam in dev.cameras:
            for st in cloud.stream_state(cam).values():
                if st.get("state") in PROBLEMS:
                    problems.append(CloudProblem(camera_id=cam.id, camera_name=cam.name, state=st["state"]))
                    break
    return CloudAccountOut(id=acc.id, name=acc.name, provider=acc.provider, login=acc.login, error=acc.error,
                           checked_at=acc.checked_at, devices=len(devs), cameras=sum(len(d.cameras) for d in devs),
                           problems=problems)


@router.get("", response_model=CloudInfo)
async def info(_: AdminUser, session: Session):
    accounts = (await session.scalars(select(CloudAccount).order_by(CloudAccount.created_at))).all()
    return CloudInfo(bridge=bool(cloud.state()), accounts=[await _out(session, a) for a in accounts])


@router.post("/accounts", response_model=CloudAccountOut, status_code=status.HTTP_201_CREATED)
async def add_account(body: CloudAccountIn, _: AdminUser, session: Session):
    login = body.login.strip()
    dup = await session.scalar(select(func.count()).select_from(CloudAccount).where(
        CloudAccount.provider == body.provider, func.lower(CloudAccount.login) == login.lower()))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "cloud_account_exists")
    acc = CloudAccount(id=uuid.uuid4(), provider=body.provider, login=login, name=body.name.strip(),
                       password_enc=encrypt_secret(body.password), feature_code=_feature_code(body.provider, login))
    try:
        await cloud.log_in(acc, body.password, body.code)
    except CloudError as exc:
        cloud.forget(acc.id)
        raise _fail(exc) from exc
    session.add(acc)
    await session.commit()
    return await _out(session, acc)


@router.put("/accounts/{account_id}", response_model=CloudAccountOut)
async def update_account(account_id: uuid.UUID, body: CloudAccountUpdate, _: AdminUser, session: Session):
    """Renames the account, or logs in again (new password, or after a lock or a code)."""
    acc = await _account(session, account_id)
    if body.name is not None:
        acc.name = body.name.strip()
    if body.password or body.code:
        try:
            await cloud.log_in(acc, body.password or None, body.code)
        except CloudError as exc:
            await session.commit()
            raise _fail(exc) from exc
        if body.password:
            acc.password_enc = encrypt_secret(body.password)
    await session.commit()
    return await _out(session, acc)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: uuid.UUID, _: AdminUser, session: Session):
    """Removes the account together with the cameras added from it."""
    acc = await _account(session, account_id)
    devs = (await session.scalars(select(Device).where(Device.cloud_account_id == acc.id))).unique().all()
    camera_ids = [c.id for d in devs for c in d.cameras]
    for dev in devs:
        await session.delete(dev)
    await session.flush()  # devices first: the account row cascades in the database
    await session.delete(acc)
    await session.commit()
    cloud.forget(account_id)
    for cid in camera_ids:
        await safe_unregister(cid)


@router.get("/accounts/{account_id}/devices", response_model=list[CloudDevice])
async def account_devices(account_id: uuid.UUID, _: AdminUser, session: Session):
    """What the account has, marking what is already in Argus."""
    acc = await _account(session, account_id)
    try:
        found = await cloud.devices(acc)
    except CloudError as exc:
        await session.commit()
        raise _fail(exc) from exc
    await session.commit()
    ours = {d.serial: d for d in (await session.scalars(
        select(Device).where(Device.cloud_account_id == acc.id))).unique().all()}
    out = []
    for d in found:
        dev = ours.get(d["serial"])
        cams = {c.channel: c.id for c in dev.cameras} if dev else {}
        out.append(CloudDevice(serial=d["serial"], name=d["name"], model=d["model"], online=d["online"],
                               encrypted=d["encrypted"], device_id=dev.id if dev else None,
                               channels=[CloudChannel(channel=c["channel"], name=c["name"],
                                                      camera_id=cams.get(c["channel"])) for c in d["channels"]]))
    return out


@router.post("/accounts/{account_id}/add", response_model=list[DeviceOut])
async def add_cameras(account_id: uuid.UUID, body: CloudAddIn, user: AdminUser, session: Session):
    """Adds the picked channels: one Argus device per cloud device, a camera per channel."""
    acc = await _account(session, account_id)
    await get_unit_in_scope(session, user, body.org_unit_id)
    try:
        found = {d["serial"]: d for d in await cloud.devices(acc)}
    except CloudError as exc:
        await session.commit()
        raise _fail(exc) from exc
    ours = {d.serial: d for d in (await session.scalars(
        select(Device).where(Device.cloud_account_id == acc.id))).unique().all()}
    touched: list[Device] = []
    new_cams: list[Camera] = []
    for pick in body.items:
        info = found.get(pick.serial)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "cloud_device_not_found")
        names = {c["channel"]: c["name"] for c in info["channels"]}
        dev = ours.get(pick.serial)
        if dev is None:
            dev = Device(name=info["name"], vendor=CameraVendor.cloud, cloud_account_id=acc.id, serial=info["serial"],
                         model=info["model"], online=info["online"], org_unit_id=body.org_unit_id)
            session.add(dev)
            ours[pick.serial] = dev
        recorder = len(names) > 1
        taken = {c.channel for c in dev.cameras}
        for ch in sorted(set(pick.channels)):
            if ch not in names or ch in taken:
                continue
            label = names[ch] or f"CH{ch}"
            cam = Camera(name=(f"{dev.name} · {label}" if recorder else dev.name)[:200], channel=ch,
                         org_unit_id=body.org_unit_id)
            dev.cameras.append(cam)
            new_cams.append(cam)
        if recorder:
            dev.kind = DeviceKind.recorder
        touched.append(dev)
    await session.commit()
    for cam in new_cams:
        await safe_register(cam)
    out = []
    for dev in touched:
        dev = await session.get(Device, dev.id, populate_existing=True)
        out.append(DeviceOut.model_validate(dev))
    return out

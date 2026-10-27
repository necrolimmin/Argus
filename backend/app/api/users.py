import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.deps import AdminUser, Session
from app.models import OrgUnit, User, UserRole
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


async def _check_unit(session, unit_id: uuid.UUID | None) -> None:
    if unit_id is not None and await session.get(OrgUnit, unit_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "org_unit_not_found")


async def _active_admins(session) -> int:
    return await session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.admin, User.is_active)
    )


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminUser, session: Session):
    return (await session.scalars(select(User).order_by(User.username))).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, _: AdminUser, session: Session):
    await _check_unit(session, body.org_unit_id)
    if await session.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "username_taken")
    user = User(
        username=body.username,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=body.role,
        org_unit_id=body.org_unit_id if body.role == UserRole.operator else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, me: AdminUser, session: Session):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")

    data = body.model_dump(exclude_unset=True)
    demoting = user.role == UserRole.admin and (
        data.get("role") == UserRole.operator or data.get("is_active") is False
    )
    if demoting and await _active_admins(session) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "last_admin")

    if "password" in data:
        password = data.pop("password")
        if password:
            user.password_hash = hash_password(password)
    if "org_unit_id" in data:
        await _check_unit(session, data["org_unit_id"])
    for key, value in data.items():
        setattr(user, key, value)

    if user.role == UserRole.admin:
        user.org_unit_id = None
    elif user.org_unit_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "operator_requires_org_unit")

    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, me: AdminUser, session: Session):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    if user.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot_delete_self")
    await session.delete(user)
    await session.commit()

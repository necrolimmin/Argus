from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import User, UserRole
from app.security import decode_access_token

Session = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def user_from_token(session: AsyncSession, token: str | None) -> User | None:
    user_id = decode_access_token(token) if token else None
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user if user and user.is_active else None


async def get_current_user(
    session: Session,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    user = await user_from_token(session, creds.credentials if creds else None)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin_only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def scope_path(user: User) -> str | None:
    """Path prefix the user may see, or None for everything (admins)."""
    if user.role == UserRole.admin:
        return None
    # An operator without a unit sees nothing; "//" matches no real path.
    return user.org_unit.path if user.org_unit else "//"


def in_scope(user: User, path: str) -> bool:
    prefix = scope_path(user)
    return prefix is None or path.startswith(prefix)


async def require_service(x_service_token: Annotated[str | None, Header()] = None) -> None:
    if x_service_token != get_settings().service_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad_service_token")

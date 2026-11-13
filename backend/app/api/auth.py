from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import CurrentUser, Session
from app.models import User
from app.schemas import CaptchaOut, LoginIn, PasswordChangeIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import login_guard

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/captcha", response_model=CaptchaOut)
async def captcha():
    if not get_settings().captcha_enabled:
        return CaptchaOut(enabled=False)
    captcha_id, image = login_guard.new_captcha()
    return CaptchaOut(enabled=True, id=captcha_id, image=image)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, session: Session):
    ip = request.client.host if request.client else ""
    wait = login_guard.locked_for(ip, body.username)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", headers={"Retry-After": str(wait)})
    if get_settings().captcha_enabled and not login_guard.check_captcha(body.captcha_id, body.captcha_answer):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "captcha_wrong")
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        login_guard.failed(ip, body.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    login_guard.succeeded(ip, body.username)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChangeIn, user: CurrentUser, session: Session):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "wrong_current_password")
    user.password_hash = hash_password(body.new_password)
    await session.commit()

import base64
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, s.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key or base64.urlsafe_b64encode(
        hashlib.sha256(s.secret_key.encode()).digest()
    ).decode()
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


# <img> tags cannot send an Authorization header, so media is served through
# short-lived signed links instead.
MEDIA_LINK_SECONDS = 6 * 60 * 60


def _media_sig(path: str, exp: int) -> str:
    msg = f"{path}:{exp}".encode()
    return hmac.new(get_settings().secret_key.encode(), msg, hashlib.sha256).hexdigest()[:32]


def media_url(path: str) -> str:
    if not path:
        return ""
    # Rounded to the hour so the same file keeps one URL for a while and the
    # browser cache actually hits.
    exp = (int(time.time()) // 3600) * 3600 + MEDIA_LINK_SECONDS
    return f"/api/media/{path}?exp={exp}&sig={_media_sig(path, exp)}"


def verify_media(path: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(_media_sig(path, exp), sig)

import asyncio
import logging
import shutil
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import FaceEvent, User, UserRole
from app.security import hash_password
from app.services.device_status import refresh_status
from app.services.media import media_root
from app.services.streams import go2rtc

log = logging.getLogger(__name__)


async def ensure_admin() -> None:
    s = get_settings()
    async with SessionLocal() as session:
        if await session.scalar(select(func.count()).select_from(User)):
            return
        session.add(
            User(
                username=s.admin_username,
                full_name="Administrator",
                password_hash=hash_password(s.admin_password),
                role=UserRole.admin,
            )
        )
        await session.commit()
        log.info("created first administrator %r", s.admin_username)


async def purge_old_events() -> None:
    days = get_settings().retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with SessionLocal() as session:
        await session.execute(delete(FaceEvent).where(FaceEvent.occurred_at < cutoff))
        await session.commit()
    # Event files sit in per-day folders, so whole days go at once.
    oldest_kept = (cutoff - timedelta(days=1)).date()
    for folder in ("events", "faces"):
        base = media_root() / folder
        if not base.is_dir():
            continue
        for day_dir in base.iterdir():
            try:
                day = date.fromisoformat(day_dir.name)
            except ValueError:
                continue
            if day < oldest_kept:
                shutil.rmtree(day_dir, ignore_errors=True)


async def _every(seconds: int, job, name: str) -> None:
    while True:
        try:
            await job()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s failed: %s", name, exc)
        await asyncio.sleep(seconds)


async def _sync_streams() -> None:
    async with SessionLocal() as session:
        await go2rtc().sync(session)


def start_background_jobs() -> list[asyncio.Task]:
    return [
        asyncio.create_task(_every(60, _sync_streams, "go2rtc sync")),
        asyncio.create_task(_every(60, refresh_status, "device status")),
        asyncio.create_task(_every(6 * 60 * 60, purge_old_events, "retention")),
    ]

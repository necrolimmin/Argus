"""Online/offline status: a TCP connect to each device's stream port."""

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select

from app.db import SessionLocal
from app.models import CameraVendor, Device


def _endpoint(dev: Device) -> tuple[str, int]:
    if dev.vendor in (CameraVendor.rtsp, CameraVendor.http, CameraVendor.other) and dev.cameras:
        url = urlsplit(dev.cameras[0].rtsp_main)
        default = 80 if url.scheme.startswith("http") else 554
        return url.hostname or dev.host, url.port or default
    if dev.vendor == CameraVendor.dvrip:
        return dev.host, dev.rtsp_port if dev.rtsp_port != 554 else 34567
    return dev.host, dev.rtsp_port


async def _reachable(host: str, port: int, timeout: float = 3) -> bool:
    if not host:
        return False
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def refresh_status() -> None:
    async with SessionLocal() as session:
        devices = (await session.scalars(select(Device))).unique().all()
        limit = asyncio.Semaphore(64)

        async def check(dev: Device) -> bool:
            async with limit:
                return await _reachable(*_endpoint(dev))

        results = await asyncio.gather(*(check(d) for d in devices))
        now = datetime.now(timezone.utc)
        for dev, online in zip(devices, results):
            dev.online = online
            if online:
                dev.last_seen_at = now
        await session.commit()

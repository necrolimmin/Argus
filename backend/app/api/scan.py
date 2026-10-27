from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import AdminUser, Session
from app.models import Device
from app.schemas import FoundOut, ScanRangeIn
from app.services import discovery, scan_client

router = APIRouter(prefix="/scan", tags=["scan"])


async def _annotate(session, found: list[dict]) -> list[FoundOut]:
    """Marks what is already in Argus, matching by MAC, serial or address."""
    devices = (await session.scalars(select(Device))).unique().all()
    by_mac = {d.mac: d for d in devices if d.mac}
    by_serial = {d.serial: d for d in devices if d.serial}
    by_host = {d.host: d for d in devices if d.host}
    out = []
    for f in found:
        item = FoundOut(**f)
        dev = by_mac.get(item.mac) or by_serial.get(item.serial) or by_host.get(item.ip)
        if dev:
            item.device_id, item.device_name = dev.id, dev.name
        out.append(item)
    return out


@router.post("/discover", response_model=list[FoundOut])
async def discover(_: AdminUser, session: Session):
    try:
        found = await scan_client.discover()
    except scan_client.ScanUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scanner_unavailable") from exc
    return await _annotate(session, found)


@router.post("/range", response_model=list[FoundOut])
async def scan_range(body: ScanRangeIn, _: AdminUser, session: Session):
    try:
        discovery.parse_ranges(body.ranges)  # validate before the long call
    except OverflowError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "range_too_large") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "range_invalid") from exc
    try:
        found = await scan_client.scan_ranges(body.ranges)
    except scan_client.ScanUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scanner_unavailable") from exc
    return await _annotate(session, found)

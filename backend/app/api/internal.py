"""Endpoints used only by the recognizer service, guarded by the service token."""

import base64
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import Session, require_service
from app.models import Camera, Employee, EmployeePhoto, EventKind, FaceEvent
from app.services import media
from app.services.events import to_out
from app.services.hub import hub
from app.services.streams import restream_url

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_service)])


async def _gallery_version(session) -> str:
    row = (
        await session.execute(
            select(func.count(EmployeePhoto.id), func.max(Employee.updated_at)).select_from(Employee)
            .outerjoin(EmployeePhoto)
        )
    ).one()
    return hashlib.sha1(f"{row[0]}:{row[1]}".encode()).hexdigest()[:16]


@router.get("/recognizer/config")
async def recognizer_config(session: Session):
    s = get_settings()
    cameras = (
        await session.scalars(select(Camera).where(Camera.enabled, Camera.face_recognition))
    ).all()
    return {
        "cameras": [
            {
                "id": str(c.id),
                "name": c.name,
                "stream_url": restream_url(c),
                "direction": c.direction.value,
                "schedule": c.schedule or [],
            }
            for c in cameras
        ],
        "dedup_seconds": s.dedup_seconds,
        "match_threshold": s.match_threshold,
        "timezone": s.timezone,
        "gallery_version": await _gallery_version(session),
    }


@router.get("/recognizer/gallery")
async def recognizer_gallery(session: Session):
    rows = await session.execute(
        select(EmployeePhoto.employee_id, EmployeePhoto.embedding)
        .join(Employee)
        .where(Employee.is_active)
    )
    gallery: dict[str, list[str]] = {}
    for employee_id, embedding in rows.all():
        gallery.setdefault(str(employee_id), []).append(base64.b64encode(embedding).decode())
    return {
        "version": await _gallery_version(session),
        "employees": [{"id": k, "embeddings": v} for k, v in gallery.items()],
    }


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def ingest_event(
    session: Session,
    camera_id: uuid.UUID = Form(...),
    kind: EventKind = Form(...),
    occurred_at: datetime = Form(...),
    image: UploadFile = Form(...),
    employee_id: uuid.UUID | None = Form(None),
    similarity: float | None = Form(None),
    face: UploadFile | None = Form(None),
    embedding: str | None = Form(None),
):
    cam = await session.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera_not_found")
    employee = await session.get(Employee, employee_id) if employee_id else None
    if kind == EventKind.recognized and employee is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "employee_not_found")
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    event = FaceEvent(
        kind=kind,
        camera_id=cam.id,
        camera_name=cam.name,
        org_path=cam.org_unit.path,
        direction=cam.direction,
        employee_id=employee.id if employee else None,
        employee_name=employee.full_name if employee else "",
        similarity=similarity,
        occurred_at=occurred_at,
        image_path=media.save_bytes("events", await image.read(), occurred_at),
    )
    if kind == EventKind.unknown:
        if face is not None:
            event.face_path = media.save_bytes("faces", await face.read(), occurred_at)
        if embedding:
            event.embedding = base64.b64decode(embedding)
    session.add(event)
    await session.commit()

    event = await session.get(FaceEvent, event.id, populate_existing=True)
    out = (await to_out(session, [event]))[0]
    await hub.publish(cam.id, {"type": "event", "event": out.model_dump(mode="json")})
    return {"id": str(event.id)}

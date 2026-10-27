import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.employees import _commit_unique, add_photo
from app.api.employees import _out as employee_out
from app.deps import AdminUser, CurrentUser, Session, in_scope, scope_path
from app.models import Employee, EventKind, FaceEvent
from app.schemas import EmployeeCreate, EmployeeOut, EventOut
from app.services import media
from app.services.events import to_out
from app.services.org import get_unit_in_scope

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
async def list_events(
    user: CurrentUser,
    session: Session,
    camera_ids: list[uuid.UUID] = Query(default=[]),
    kind: EventKind | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    limit: int = 50,
):
    """Newest first. Page back by passing the last `occurred_at` as `before`."""
    query = select(FaceEvent).order_by(FaceEvent.occurred_at.desc())
    prefix = scope_path(user)
    if prefix is not None:
        query = query.where(FaceEvent.org_path.startswith(prefix))
    if camera_ids:
        query = query.where(FaceEvent.camera_id.in_(camera_ids))
    if kind is not None:
        query = query.where(FaceEvent.kind == kind)
    if since is not None:
        query = query.where(FaceEvent.occurred_at >= since)
    if before is not None:
        query = query.where(FaceEvent.occurred_at < before)
    events = (await session.scalars(query.limit(min(max(limit, 1), 200)))).unique().all()
    return await to_out(session, list(events))


@router.post("/{event_id}/employee", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def employee_from_event(event_id: uuid.UUID, body: EmployeeCreate, user: AdminUser, session: Session):
    """Creates an employee from an unknown face, using its crop as the first photo."""
    event = await session.get(FaceEvent, event_id)
    if event is None or not in_scope(user, event.org_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event_not_found")
    if event.kind != EventKind.unknown or not event.embedding or not event.face_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "event_has_no_face")
    if event.employee_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "event_already_linked")
    await get_unit_in_scope(session, user, body.org_unit_id)

    emp = Employee(**body.model_dump())
    session.add(emp)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "personnel_number_taken") from exc
    await add_photo(session, emp, media.read_bytes(event.face_path), event.embedding)
    event.employee_id = emp.id
    event.employee_name = emp.full_name
    await _commit_unique(session)
    return employee_out(await session.get(Employee, emp.id, populate_existing=True))

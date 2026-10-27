from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventKind, FaceEvent
from app.schemas import EventEmployee, EventOut
from app.security import media_url
from app.services.org import unit_labels


async def to_out(session: AsyncSession, events: list[FaceEvent]) -> list[EventOut]:
    employees = [e.employee for e in events if e.employee]
    labels = await unit_labels(session, [emp.org_unit for emp in employees])
    out = []
    for e in events:
        emp = e.employee
        recognized = e.kind == EventKind.recognized
        out.append(
            EventOut(
                id=e.id,
                kind=e.kind,
                camera_id=e.camera_id,
                camera_name=e.camera_name,
                direction=e.direction,
                occurred_at=e.occurred_at,
                similarity=e.similarity,
                image_url=media_url(e.image_path),
                face_url=media_url(e.face_path),
                employee=EventEmployee(
                    id=emp.id,
                    full_name=emp.full_name,
                    position=emp.position,
                    org_unit=labels.get(emp.org_unit_id, ""),
                )
                if emp and recognized
                else None,
                linked_employee_name=emp.full_name if emp and not recognized else "",
            )
        )
    return out

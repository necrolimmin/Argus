import uuid
from collections import Counter

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.deps import AdminUser, CurrentUser, Session, scope_path
from app.models import LEVEL_ORDER, Camera, Employee, OrgUnit, User
from app.schemas import OrgUnitCreate, OrgUnitOut, OrgUnitUpdate
from app.services.org import child_path, get_unit_in_scope, path_ids

router = APIRouter(prefix="/org-units", tags=["org"])


async def _counts(session, model) -> Counter:
    rows = await session.execute(select(model.org_unit_id, func.count()).group_by(model.org_unit_id))
    return Counter(dict(rows.all()))


@router.get("", response_model=list[OrgUnitOut])
async def list_units(user: CurrentUser, session: Session):
    """Flat list of every unit the user may see; the client builds the tree."""
    query = select(OrgUnit).order_by(OrgUnit.name)
    prefix = scope_path(user)
    if prefix is not None:
        query = query.where(OrgUnit.path.startswith(prefix))
    units = (await session.scalars(query)).all()

    cams, emps = await _counts(session, Camera), await _counts(session, Employee)
    total_cams, total_emps = Counter(), Counter()
    for u in units:
        for ancestor in path_ids(u.path):
            total_cams[ancestor] += cams[u.id]
            total_emps[ancestor] += emps[u.id]

    return [
        OrgUnitOut(
            id=u.id,
            parent_id=u.parent_id,
            level=u.level,
            name=u.name,
            camera_count=total_cams[u.id],
            employee_count=total_emps[u.id],
        )
        for u in units
    ]


@router.post("", response_model=OrgUnitOut, status_code=status.HTTP_201_CREATED)
async def create_unit(body: OrgUnitCreate, user: AdminUser, session: Session):
    parent = None
    level = LEVEL_ORDER[0]
    if body.parent_id is not None:
        parent = await get_unit_in_scope(session, user, body.parent_id)
        depth = LEVEL_ORDER.index(parent.level)
        if depth == len(LEVEL_ORDER) - 1:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "section_has_no_children")
        level = LEVEL_ORDER[depth + 1]

    unit_id = uuid.uuid4()
    unit = OrgUnit(
        id=unit_id,
        parent_id=parent.id if parent else None,
        level=level,
        name=body.name.strip(),
        path=child_path(parent.path if parent else None, unit_id),
    )
    session.add(unit)
    await session.commit()
    return OrgUnitOut.model_validate(unit)


@router.patch("/{unit_id}", response_model=OrgUnitOut)
async def rename_unit(unit_id: uuid.UUID, body: OrgUnitUpdate, user: AdminUser, session: Session):
    unit = await get_unit_in_scope(session, user, unit_id)
    unit.name = body.name.strip()
    await session.commit()
    return OrgUnitOut.model_validate(unit)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(unit_id: uuid.UUID, user: AdminUser, session: Session):
    """Deletes a unit and its empty sub-units.

    Refused while any camera, employee or operator is attached anywhere in
    the subtree: they have to be moved or removed first.
    """
    unit = await get_unit_in_scope(session, user, unit_id)
    subtree = select(OrgUnit.id).where(OrgUnit.path.startswith(unit.path))

    for model, code in ((Camera, "unit_has_cameras"), (Employee, "unit_has_employees"), (User, "unit_has_users")):
        used = await session.scalar(
            select(func.count()).select_from(model).where(model.org_unit_id.in_(subtree))
        )
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, code)

    # Deepest first, so no parent is removed while it still has children.
    units = (await session.scalars(select(OrgUnit).where(OrgUnit.path.startswith(unit.path)))).all()
    for u in sorted(units, key=lambda u: len(u.path), reverse=True):
        await session.delete(u)
        await session.flush()
    await session.commit()

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import in_scope
from app.models import OrgUnit, User


def child_path(parent_path: str | None, unit_id: uuid.UUID) -> str:
    return f"{parent_path or '/'}{unit_id.hex}/"


def path_ids(path: str) -> list[uuid.UUID]:
    return [uuid.UUID(part) for part in path.strip("/").split("/") if part]


async def get_unit_in_scope(session: AsyncSession, user: User, unit_id: uuid.UUID) -> OrgUnit:
    unit = await session.get(OrgUnit, unit_id)
    if unit is None or not in_scope(user, unit.path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "org_unit_not_found")
    return unit


async def unit_labels(session: AsyncSession, units: list[OrgUnit]) -> dict[uuid.UUID, str]:
    """Readable "Branch / Enterprise / Section" label for each unit.

    The company name is left out: within one screen it is almost always the
    same, and it would push the useful part off the line.
    """
    needed = {i for u in units for i in path_ids(u.path)}
    if not needed:
        return {}
    rows = await session.scalars(select(OrgUnit).where(OrgUnit.id.in_(needed)))
    names = {u.id: u.name for u in rows}
    labels = {}
    for u in units:
        chain = [names.get(i, "") for i in path_ids(u.path)]
        labels[u.id] = " / ".join(chain[1:] or chain)
    return labels

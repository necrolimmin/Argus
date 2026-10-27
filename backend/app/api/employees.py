import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, CurrentUser, Session, in_scope, scope_path
from app.models import MAX_PHOTOS, Employee, EmployeePhoto, OrgUnit
from app.schemas import EmployeeCreate, EmployeeOut, EmployeePage, EmployeeUpdate, PhotoOut
from app.security import media_url
from app.services import media
from app.services.org import get_unit_in_scope
from app.services.recognizer import FaceCheckError, RecognizerUnavailable, embed_photo

router = APIRouter(prefix="/employees", tags=["employees"])

MAX_UPLOAD = 10 * 1024 * 1024


def _out(emp: Employee) -> EmployeeOut:
    return EmployeeOut(
        id=emp.id,
        full_name=emp.full_name,
        personnel_number=emp.personnel_number,
        position=emp.position,
        phone=emp.phone,
        org_unit_id=emp.org_unit_id,
        is_active=emp.is_active,
        photos=[PhotoOut(id=p.id, url=media_url(p.image_path)) for p in emp.photos],
    )


async def _employee_in_scope(session, user, employee_id: uuid.UUID) -> Employee:
    emp = await session.get(Employee, employee_id)
    if emp is None or not in_scope(user, emp.org_unit.path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "employee_not_found")
    return emp


async def _commit_unique(session) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "personnel_number_taken") from exc


@router.get("", response_model=EmployeePage)
async def list_employees(
    user: CurrentUser,
    session: Session,
    org_unit_id: uuid.UUID | None = None,
    q: str = "",
    active: bool | None = None,
    offset: int = 0,
    limit: int = 50,
):
    query = select(Employee).join(Employee.org_unit)
    prefix = scope_path(user)
    if prefix is not None:
        query = query.where(OrgUnit.path.startswith(prefix))
    if org_unit_id is not None:
        unit = await get_unit_in_scope(session, user, org_unit_id)
        query = query.where(OrgUnit.path.startswith(unit.path))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Employee.full_name.ilike(like),
                Employee.personnel_number.ilike(like),
                Employee.position.ilike(like),
            )
        )
    if active is not None:
        query = query.where(Employee.is_active == active)

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Employee.full_name).offset(max(offset, 0)).limit(min(max(limit, 1), 200))
    )
    return EmployeePage(items=[_out(e) for e in rows.unique().all()], total=total or 0)


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: uuid.UUID, user: CurrentUser, session: Session):
    return _out(await _employee_in_scope(session, user, employee_id))


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(body: EmployeeCreate, user: AdminUser, session: Session):
    await get_unit_in_scope(session, user, body.org_unit_id)
    emp = Employee(**body.model_dump())
    session.add(emp)
    await _commit_unique(session)
    return _out(await session.get(Employee, emp.id, populate_existing=True))


@router.put("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID, body: EmployeeUpdate, user: AdminUser, session: Session
):
    emp = await _employee_in_scope(session, user, employee_id)
    await get_unit_in_scope(session, user, body.org_unit_id)
    for key, value in body.model_dump().items():
        setattr(emp, key, value)
    await _commit_unique(session)
    return _out(await session.get(Employee, emp.id, populate_existing=True))


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(employee_id: uuid.UUID, user: AdminUser, session: Session):
    emp = await _employee_in_scope(session, user, employee_id)
    paths = [p.image_path for p in emp.photos]
    await session.delete(emp)
    await session.commit()
    for path in paths:
        media.delete_file(path)


async def add_photo(session, emp: Employee, image: bytes, embedding: bytes) -> EmployeePhoto:
    photo = EmployeePhoto(
        employee_id=emp.id,
        image_path=media.save_bytes("employees", image),
        embedding=embedding,
    )
    session.add(photo)
    # Bumps updated_at, which the recognizer watches to reload its gallery.
    emp.updated_at = func.now()
    return photo


@router.post("/{employee_id}/photos", response_model=EmployeeOut)
async def upload_photo(employee_id: uuid.UUID, file: UploadFile, user: AdminUser, session: Session):
    emp = await _employee_in_scope(session, user, employee_id)
    if len(emp.photos) >= MAX_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT, "too_many_photos")
    image = await file.read(MAX_UPLOAD + 1)
    if len(image) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")
    try:
        embedding = await embed_photo(image, file.filename or "photo.jpg")
    except FaceCheckError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code) from exc
    except RecognizerUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "recognizer_unavailable") from exc

    await add_photo(session, emp, image, embedding)
    await session.commit()
    return _out(await session.get(Employee, emp.id, populate_existing=True))


@router.delete("/{employee_id}/photos/{photo_id}", response_model=EmployeeOut)
async def delete_photo(employee_id: uuid.UUID, photo_id: uuid.UUID, user: AdminUser, session: Session):
    emp = await _employee_in_scope(session, user, employee_id)
    photo = next((p for p in emp.photos if p.id == photo_id), None)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo_not_found")
    path = photo.image_path
    emp.photos.remove(photo)
    emp.updated_at = func.now()
    await session.commit()
    media.delete_file(path)
    return _out(await session.get(Employee, emp.id, populate_existing=True))

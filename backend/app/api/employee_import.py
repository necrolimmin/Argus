"""Employees from a filled-in Excel template, photos included.

Three steps, so a big file is sent once and checked before anything is saved:

1. POST /employees/import/preview — the file is stored, its rows read and the
   pictures pulled out next to it; the rows come back for the person to look at.
2. POST /employees/import — saves the rows in the background (each photo has
   to pass the face check, which takes a moment per photo).
3. GET /employees/import/{token} — progress and, at the end, what was skipped.

Photos come from the workbook itself (pictures in the rows) or, for a .zip,
from image files named by personnel number: 123.jpg, 123_2.jpg.
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import posixpath
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.db import SessionLocal
from app.deps import AdminUser, Session
from app.models import MAX_PHOTOS, Employee, OrgUnit
from app.security import media_url
from app.services import media
from app.services.recognizer import FaceCheckError, RecognizerUnavailable, embed_photo
from app.services.xlsx_images import images_by_row

log = logging.getLogger(__name__)
router = APIRouter(prefix="/employees/import", tags=["employees"])

MAX_FILE = 300 * 1024 * 1024
MAX_PHOTO = 10 * 1024 * 1024
MAX_ROWS = 2000
KEEP_SECONDS = 24 * 3600
HEADER = ["Фамилия", "Имя", "Отчество", "Табельный номер", "Должность", "Телефон", "Подразделение", "Фото"]
IMAGE_EXT = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".bmp": "bmp", ".webp": "webp"}


class ImportPhoto(BaseModel):
    path: str
    url: str = ""


class EmployeeImportRow(BaseModel):
    row: int
    full_name: str = ""
    personnel_number: str | None = None
    position: str = ""
    phone: str = ""
    org_path: str = ""
    org_unit_id: uuid.UUID | None = None
    action: Literal["create", "update"] = "create"
    photos: list[ImportPhoto] = []
    errors: list[str] = []
    warnings: list[str] = []


class ImportPreview(BaseModel):
    token: str
    rows: list[EmployeeImportRow]


class ImportStart(BaseModel):
    token: str


class PhotoProblem(BaseModel):
    row: int
    full_name: str
    code: str


class ImportProgress(BaseModel):
    total: int
    done: int = 0
    created: int = 0
    updated: int = 0
    photos: int = 0
    skipped_rows: list[int] = []
    photo_problems: list[PhotoProblem] = []
    finished: bool = False


JOBS: dict[str, ImportProgress] = {}
_tasks: set[asyncio.Task] = set()


def _root() -> Path:
    return media.media_root() / "imports"


def _token_dir(token: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    return _root() / token


def _drop_stale() -> None:
    root = _root()
    if not root.is_dir():
        return
    for d in root.iterdir():
        if d.is_dir() and time.time() - d.stat().st_mtime > KEEP_SECONDS and d.name not in JOBS:
            shutil.rmtree(d, ignore_errors=True)


# --- the template ---------------------------------------------------------------


async def _unit_paths(session) -> list[tuple[OrgUnit, str]]:
    units = (await session.scalars(select(OrgUnit))).all()
    by_id = {u.id: u for u in units}

    def chain(u: OrgUnit) -> str:
        names = []
        while u is not None:
            names.append(u.name)
            u = by_id.get(u.parent_id)
        return " / ".join(reversed(names))

    return sorted(((u, chain(u)) for u in units), key=lambda p: p[1].lower())


@router.get("/template")
async def import_template(_: AdminUser, session: Session):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Сотрудники"
    ws.append(HEADER)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDEFGH", (18, 16, 18, 16, 22, 16, 44, 16)):
        ws.column_dimensions[col].width = width
    # Tall rows, so a photo dropped into column H stays inside its row.
    for r in range(2, 302):
        ws.row_dimensions[r].height = 80
    ws.freeze_panes = "A2"

    paths = [p for _, p in await _unit_paths(session)]
    units = wb.create_sheet("Подразделения")
    units.append(["Подразделение"])
    units["A1"].font = Font(bold=True)
    units.column_dimensions["A"].width = 60
    for p in paths:
        units.append([p])
    if paths:
        dv = DataValidation(type="list", formula1=f"='Подразделения'!$A$2:$A${len(paths) + 1}", allow_blank=True)
        dv.error, dv.showErrorMessage = "Выберите подразделение из списка", False
        ws.add_data_validation(dv)
        dv.add("G2:G2001")

    howto = wb.create_sheet("Как заполнить")
    howto.column_dimensions["A"].width = 100
    for line in (
        "Одна строка — один сотрудник. Первая строка с названиями колонок остаётся как есть.",
        "Обязательно: фамилия или имя и подразделение. Подразделение выбирается из списка в ячейке.",
        "Табельный номер нужен, чтобы при повторной загрузке обновить сотрудника, а не создать второго.",
        "Фото: вставьте снимок лица в колонку «Фото» в строке сотрудника (Вставка → Рисунок или «Поместить в ячейку»).",
        "Можно несколько фото в одной строке, до 5 на человека. Лицо должно быть одно, хорошо видно, без очков от солнца.",
        "Чтобы Excel не ухудшал фото: Файл → Параметры → Дополнительно → «Не сжимать изображения в файле».",
        "Много сотрудников? Сохраните таблицу без фото и упакуйте в .zip вместе с фотографиями,",
        "    названными по табельному номеру: 123.jpg, 123_2.jpg. Или впишите имя файла в колонку «Фото».",
    ):
        howto.append([line])
        howto.cell(howto.max_row, 1).alignment = Alignment(wrap_text=True)

    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="argus-employees.xlsx"'},
    )


# --- reading the file -------------------------------------------------------------


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return "" if s.startswith("#") and s.endswith("!") else s  # "#VALUE!" under an in-cell picture


def _xlsx_rows(data: bytes) -> list[tuple[int, list[str]]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for cells in wb.worksheets[0].iter_rows(min_row=2):
        cells = [c for c in cells if getattr(c, "row", None)]
        if cells:
            row = [""] * 8
            for c in cells:
                if 1 <= c.column <= 8:
                    row[c.column - 1] = _text(c.value)
            out.append((cells[0].row, row))
    return out


def _csv_rows(data: bytes) -> list[tuple[int, list[str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    return [(i, ([c.strip() for c in r] + [""] * 8)[:8]) for i, r in enumerate(rows[1:], start=2)]


def _kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class _Unresolved:
    """Org paths as people write them: the full chain, or just its tail."""

    def __init__(self, pairs: list[tuple[OrgUnit, str]]):
        self.chains = [(u.id, tuple(p.strip().lower() for p in path.split(" / "))) for u, path in pairs]

    def __call__(self, text: str) -> uuid.UUID | None:
        parts = tuple(p.strip().lower() for p in re.split(r"[/\\>]", text) if p.strip())
        if not parts:
            return None
        exact = [i for i, c in self.chains if c == parts]
        if exact:
            return exact[0]
        tail = [i for i, c in self.chains if c[-len(parts):] == parts]
        return tail[0] if len(tail) == 1 else None


def _pack_index(pack: zipfile.ZipFile) -> dict[str, str]:
    """Image files in a .zip: lower-case name without folder (with and without extension) → member."""
    out = {}
    for name in pack.namelist():
        base = posixpath.basename(name)
        stem, ext = posixpath.splitext(base.lower())
        if ext in IMAGE_EXT and not name.startswith("__MACOSX/"):
            out.setdefault(base.lower(), name)
            out.setdefault(stem, name)
    return out


def _by_number(index: dict[str, str], number: str) -> list[str]:
    n = number.lower()
    found = [m for key, m in index.items() if "." not in key and (key == n or re.match(rf"{re.escape(n)}[ _\-(]", key))]
    return sorted(set(found))


async def _preview(token: str, filename: str, src: Path, session) -> list[EmployeeImportRow]:
    folder = src.parent
    name = filename.lower()
    data = src.read_bytes()
    book: zipfile.ZipFile | None = None
    pack: zipfile.ZipFile | None = None
    if name.endswith(".zip"):
        pack = zipfile.ZipFile(src)
        sheets = [n for n in pack.namelist() if n.lower().endswith((".xlsx", ".csv")) and not n.startswith("__MACOSX/")
                  and not posixpath.basename(n).startswith("~$")]
        if not sheets:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "import_no_table")
        data, name = pack.read(sheets[0]), sheets[0].lower()
    if name.endswith((".xlsx", ".xlsm")):
        book = zipfile.ZipFile(io.BytesIO(data))
        table = _xlsx_rows(data)
        pictures = images_by_row(book)
    else:
        table = _csv_rows(data)
        pictures = {}
    index = _pack_index(pack) if pack else {}

    resolve = _Unresolved(await _unit_paths(session))
    numbers = {e.personnel_number: e for e in (await session.scalars(
        select(Employee).where(Employee.personnel_number.is_not(None)))).all()}
    seen: set[str] = set()
    rows = []
    for row_no, cells in table:
        last, first, middle, number, position, phone, org_path, photo_cell = cells
        if not any(cells) and row_no not in pictures:
            continue
        existing = None
        r = EmployeeImportRow(
            row=row_no,
            full_name=" ".join(p for p in (last, first, middle) if p)[:200],
            personnel_number=number[:50] or None,
            position=position[:200],
            phone=phone[:50],
            org_path=org_path,
            org_unit_id=resolve(org_path),
        )
        if not r.full_name:
            r.errors.append("name_required")
        if not org_path:
            r.errors.append("unit_required")
        elif r.org_unit_id is None:
            r.errors.append("unit_not_found")
        if r.personnel_number:
            if r.personnel_number in seen:
                r.errors.append("number_repeated")
            seen.add(r.personnel_number)
            existing = numbers.get(r.personnel_number)
            if existing is not None:
                r.action = "update"
        free = MAX_PHOTOS - (len(existing.photos) if r.action == "update" else 0)

        sources: list[tuple[zipfile.ZipFile, str]] = [(book, p) for p in pictures.get(row_no, [])]
        if pack:
            named = [n.strip().lower() for n in re.split(r"[,;\n]", photo_cell) if n.strip()]
            for n in named:
                member = index.get(n) or index.get(posixpath.splitext(n)[0])
                if member:
                    sources.append((pack, member))
                elif "photo_not_found" not in r.warnings:
                    r.warnings.append("photo_not_found")
            if not named and r.personnel_number:
                sources += [(pack, m) for m in _by_number(index, r.personnel_number)]

        for z, member in sources:
            info = z.getinfo(member)
            if info.file_size > MAX_PHOTO:
                r.warnings.append("photo_too_large")
                continue
            image = z.read(member)
            kind = _kind(image)
            if kind is None:
                r.warnings.append("photo_format")
                continue
            if len(r.photos) >= max(free, 0):
                if "too_many_photos" not in r.warnings:
                    r.warnings.append("too_many_photos")
                continue
            rel = f"imports/{token}/r{row_no}-{len(r.photos) + 1}.{kind}"
            (folder / posixpath.basename(rel)).write_bytes(image)
            r.photos.append(ImportPhoto(path=rel, url=media_url(rel)))
        r.warnings = list(dict.fromkeys(r.warnings))
        rows.append(r)
        if len(rows) > MAX_ROWS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "import_too_many_rows")
    return rows


@router.post("/preview", response_model=ImportPreview)
async def import_preview(file: UploadFile, _: AdminUser, session: Session):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv", ".zip")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "import_unreadable")
    _drop_stale()
    token = uuid.uuid4().hex
    folder = _root() / token
    folder.mkdir(parents=True)
    src = folder / ("source" + Path(name).suffix)
    size = 0
    with src.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE:
                out.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "import_too_large")
            out.write(chunk)
    try:
        rows = await _preview(token, name, src, session)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001  (corrupt workbook or zip)
        shutil.rmtree(folder, ignore_errors=True)
        log.info("employee import unreadable: %s", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "import_unreadable") from exc
    src.unlink(missing_ok=True)
    (folder / "rows.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]), encoding="utf-8")
    return ImportPreview(token=token, rows=rows)


# --- saving -----------------------------------------------------------------------


async def _save_row(r: EmployeeImportRow, job: ImportProgress, state: dict) -> None:
    from app.api.employees import add_photo

    async with SessionLocal() as session:
        if await session.get(OrgUnit, r.org_unit_id) is None:
            job.skipped_rows.append(r.row)
            return
        emp = None
        if r.personnel_number:
            emp = await session.scalar(select(Employee).where(Employee.personnel_number == r.personnel_number))
        if emp is None:
            emp = Employee(full_name=r.full_name, personnel_number=r.personnel_number, position=r.position,
                           phone=r.phone, org_unit_id=r.org_unit_id)
            session.add(emp)
            await session.flush()
            job.created += 1
        else:
            emp.full_name, emp.org_unit_id = r.full_name, r.org_unit_id
            emp.position = r.position or emp.position
            emp.phone = r.phone or emp.phone
            job.updated += 1
        await session.commit()
        emp = await session.get(Employee, emp.id, populate_existing=True)

        known = set()
        for p in emp.photos:
            try:
                known.add(hashlib.sha256(media.read_bytes(p.image_path)).digest())
            except OSError:
                pass
        count = len(emp.photos)
        for photo in r.photos:
            image = (media.media_root() / photo.path).read_bytes()
            digest = hashlib.sha256(image).digest()
            if digest in known or count >= MAX_PHOTOS:
                continue
            if state.get("recognizer_down"):
                job.photo_problems.append(PhotoProblem(row=r.row, full_name=r.full_name, code="recognizer_unavailable"))
                continue
            try:
                embedding = await embed_photo(image, posixpath.basename(photo.path))
            except FaceCheckError as exc:
                job.photo_problems.append(PhotoProblem(row=r.row, full_name=r.full_name, code=exc.code))
                continue
            except RecognizerUnavailable:
                state["recognizer_down"] = True
                job.photo_problems.append(PhotoProblem(row=r.row, full_name=r.full_name, code="recognizer_unavailable"))
                continue
            await add_photo(session, emp, image, embedding)
            await session.commit()
            known.add(digest)
            count += 1
            job.photos += 1


async def _run(token: str, rows: list[EmployeeImportRow]) -> None:
    job = JOBS[token]
    state: dict = {}
    try:
        for r in rows:
            try:
                await _save_row(r, job, state)
            except Exception:  # noqa: BLE001  (one bad row must not stop the rest)
                log.exception("employee import: row %s failed", r.row)
                job.skipped_rows.append(r.row)
            job.done += 1
    finally:
        job.finished = True
        shutil.rmtree(_root() / token, ignore_errors=True)
        # The result stays readable for a while after the files are gone.
        await asyncio.sleep(3600)
        JOBS.pop(token, None)


@router.post("", response_model=ImportProgress, status_code=status.HTTP_202_ACCEPTED)
async def import_employees(body: ImportStart, _: AdminUser):
    folder = _token_dir(body.token)
    if body.token in JOBS:
        return JOBS[body.token]
    manifest = folder / "rows.json"
    if not manifest.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    rows = [EmployeeImportRow(**r) for r in json.loads(manifest.read_text(encoding="utf-8"))]
    good = [r for r in rows if not r.errors]
    job = JOBS[body.token] = ImportProgress(total=len(good), skipped_rows=[r.row for r in rows if r.errors])
    task = asyncio.create_task(_run(body.token, good))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


@router.get("/{token}", response_model=ImportProgress)
async def import_progress(token: str, _: AdminUser):
    _token_dir(token)
    job = JOBS.get(token)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import_not_found")
    return job


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def import_cancel(token: str, _: AdminUser):
    """Forget a preview that will not be imported."""
    if token not in JOBS:
        shutil.rmtree(_token_dir(token), ignore_errors=True)

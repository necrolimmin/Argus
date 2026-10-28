import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import CameraVendor, DeviceKind, Direction, EventKind, OrgLevel, StreamQuality, UserRole


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth & users ---------------------------------------------------------


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORM):
    id: uuid.UUID
    username: str
    full_name: str
    role: UserRole
    org_unit_id: uuid.UUID | None
    is_active: bool


class TokenOut(BaseModel):
    access_token: str
    user: UserOut


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    full_name: str = Field(default="", max_length=200)
    password: str = Field(min_length=6, max_length=128)
    role: UserRole
    org_unit_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _operator_needs_unit(self):
        if self.role == UserRole.operator and self.org_unit_id is None:
            raise ValueError("operator_requires_org_unit")
        return self


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: UserRole | None = None
    org_unit_id: uuid.UUID | None = None
    is_active: bool | None = None


# --- org structure --------------------------------------------------------


class OrgUnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class OrgUnitUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrgUnitOut(ORM):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: OrgLevel
    name: str
    # Totals for this unit and everything below it.
    camera_count: int = 0
    employee_count: int = 0


# --- cameras --------------------------------------------------------------

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleWindow(BaseModel):
    days: list[int] = Field(min_length=1)  # ISO weekday, 1 = Monday
    start: str
    end: str

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("days must be 1..7")
        return sorted(set(v))

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("time must be HH:MM")
        return v


class CameraUpdate(BaseModel):
    """Settings of one channel. Connection details live on its device."""

    name: str = Field(min_length=1, max_length=200)
    org_unit_id: uuid.UUID
    face_recognition: bool = False
    direction: Direction = Direction.none
    schedule: list[ScheduleWindow] = []
    recognition_stream: StreamQuality = StreamQuality.sub
    enabled: bool = True
    rtsp_main: str = Field(default="", max_length=1000)
    rtsp_sub: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _direction_needs_faces(self):
        if not self.face_recognition:
            self.direction = Direction.none
        return self


class CameraOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    name: str
    channel: int
    rtsp_main: str
    rtsp_sub: str
    org_unit_id: uuid.UUID
    face_recognition: bool
    direction: Direction
    schedule: list[ScheduleWindow]
    recognition_stream: StreamQuality
    enabled: bool
    missing: bool


# --- devices --------------------------------------------------------------

URL_VENDORS = (CameraVendor.rtsp, CameraVendor.http, CameraVendor.other)


class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    username: str = Field(default="", max_length=100)
    # Empty on update keeps the stored password.
    password: str = Field(default="", max_length=200)


class CredentialOut(ORM):
    id: uuid.UUID
    name: str
    username: str
    device_count: int = 0


class Connection(BaseModel):
    """How to reach a device; shared by the check and the create calls."""

    vendor: CameraVendor
    host: str = Field(default="", max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    http_port: int = Field(default=80, ge=1, le=65535)
    credential_id: uuid.UUID | None = None
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=200)
    # Required for raw RTSP / HTTP devices.
    rtsp_main: str = Field(default="", max_length=1000)
    rtsp_sub: str = Field(default="", max_length=1000)
    # For recorders whose channel list cannot be read (e.g. XMeye).
    channel_count: int | None = Field(default=None, ge=1, le=256)

    @field_validator("host")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _target(self):
        if self.vendor in URL_VENDORS:
            if not self.rtsp_main:
                raise ValueError("rtsp_main_required")
        elif not self.host:
            raise ValueError("host_required")
        return self


class ProbeChannelOut(BaseModel):
    channel: int
    name: str
    rtsp_main: str
    rtsp_sub: str
    ip: str
    # Already in Argus: this device's own camera, or another device at the
    # IP a recorder reports for this channel.
    camera_id: uuid.UUID | None = None
    duplicate_of: str = ""


class DuplicateOut(BaseModel):
    device_id: uuid.UUID
    name: str
    reason: str  # serial | mac | host


class ProbeOut(BaseModel):
    ok: bool
    error: str
    kind: DeviceKind
    name: str
    model: str
    serial: str
    mac: str
    firmware: str
    codec: str
    rtsp_port: int | None = None
    channels: list[ProbeChannelOut]
    snapshot: str | None  # data: URL
    warnings: list[str]
    duplicates: list[DuplicateOut] = []


class ChannelIn(BaseModel):
    channel: int = Field(ge=1, le=256)
    name: str = Field(min_length=1, max_length=200)
    # Defaults to the device's unit.
    org_unit_id: uuid.UUID | None = None
    rtsp_main: str = Field(default="", max_length=1000)
    rtsp_sub: str = Field(default="", max_length=1000)


class DeviceCreate(Connection):
    name: str = Field(min_length=1, max_length=200)
    kind: DeviceKind = DeviceKind.camera
    org_unit_id: uuid.UUID
    model: str = Field(default="", max_length=200)
    serial: str = Field(default="", max_length=100)
    mac: str = Field(default="", max_length=32)
    firmware: str = Field(default="", max_length=200)
    channels: list[ChannelIn] = Field(min_length=1, max_length=256)


class DeviceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    org_unit_id: uuid.UUID
    host: str = Field(default="", max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    http_port: int = Field(default=80, ge=1, le=65535)
    credential_id: uuid.UUID | None = None
    username: str = Field(default="", max_length=100)
    # Empty keeps the stored password.
    password: str = Field(default="", max_length=200)


class DeviceOut(ORM):
    id: uuid.UUID
    name: str
    kind: DeviceKind
    vendor: CameraVendor
    host: str
    rtsp_port: int
    http_port: int
    credential_id: uuid.UUID | None
    username: str
    has_password: bool = False
    org_unit_id: uuid.UUID
    model: str
    serial: str
    mac: str
    firmware: str
    online: bool | None
    last_seen_at: datetime | None
    cameras: list[CameraOut]


class ChannelsIn(BaseModel):
    channels: list[ChannelIn] = Field(min_length=1, max_length=256)


class BulkTarget(BaseModel):
    vendor: CameraVendor
    host: str = Field(min_length=1, max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    http_port: int = Field(default=80, ge=1, le=65535)
    name: str = Field(default="", max_length=200)


class BulkCreate(BaseModel):
    targets: list[BulkTarget] = Field(min_length=1, max_length=500)
    org_unit_id: uuid.UUID
    credential_id: uuid.UUID | None = None
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=200)


class BulkResult(BaseModel):
    host: str
    ok: bool
    error: str = ""
    device_id: uuid.UUID | None = None
    cameras: int = 0


# --- scanning -------------------------------------------------------------


class ScanRangeIn(BaseModel):
    ranges: list[str] = Field(min_length=1, max_length=32)


class FoundOut(BaseModel):
    ip: str
    vendor: str
    model: str
    name: str
    mac: str
    serial: str
    activated: bool | None
    http_port: int | None
    rtsp_port: int | None
    open_ports: list[int]
    sources: list[str]
    device_id: uuid.UUID | None = None
    device_name: str = ""


# --- import ---------------------------------------------------------------


class ImportRow(BaseModel):
    row: int
    name: str = ""
    vendor: str = ""
    host: str = ""
    port: int | None = None
    username: str = ""
    password: str = ""
    channel: int = 1
    org_path: str = ""
    org_unit_id: uuid.UUID | None = None
    face_recognition: bool = False
    direction: Direction = Direction.none
    errors: list[str] = []


class ImportIn(BaseModel):
    rows: list[ImportRow] = Field(min_length=1, max_length=2000)


# --- employees ------------------------------------------------------------


class EmployeeBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    personnel_number: str | None = Field(default=None, max_length=50)
    position: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=50)
    org_unit_id: uuid.UUID
    is_active: bool = True

    @field_validator("personnel_number")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(EmployeeBase):
    pass


class PhotoOut(BaseModel):
    id: uuid.UUID
    url: str


class EmployeeOut(ORM):
    id: uuid.UUID
    full_name: str
    personnel_number: str | None
    position: str
    phone: str
    org_unit_id: uuid.UUID
    is_active: bool
    photos: list[PhotoOut] = []


class EmployeePage(BaseModel):
    items: list[EmployeeOut]
    total: int


# --- events ---------------------------------------------------------------


class EventEmployee(BaseModel):
    id: uuid.UUID
    full_name: str
    position: str
    org_unit: str


class EventOut(BaseModel):
    id: uuid.UUID
    kind: EventKind
    camera_id: uuid.UUID | None
    camera_name: str
    direction: Direction
    occurred_at: datetime
    similarity: float | None
    image_url: str
    # Unknown only: the face crop that "add as employee" would use.
    face_url: str = ""
    employee: EventEmployee | None
    # Unknown events that an admin turned into an employee.
    linked_employee_name: str = ""

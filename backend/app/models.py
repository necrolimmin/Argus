import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(cls: type[enum.Enum]) -> Enum:
    # Stored as plain strings so adding a value never needs an ALTER TYPE.
    return Enum(cls, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])


class OrgLevel(str, enum.Enum):
    company = "company"
    branch = "branch"
    enterprise = "enterprise"
    section = "section"


LEVEL_ORDER = [OrgLevel.company, OrgLevel.branch, OrgLevel.enterprise, OrgLevel.section]


class OrgUnit(Base):
    """One node of the strict Company → Branch → Enterprise → Section tree.

    `path` is a materialized path of hex ids ("/a/b/c/"), so a whole subtree
    is a single indexed prefix match.
    """

    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("org_units.id", ondelete="RESTRICT"), index=True
    )
    level: Mapped[OrgLevel] = mapped_column(_enum(OrgLevel))
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(140), index=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    # Operators see only this unit and everything below it.
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("org_units.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    org_unit: Mapped[OrgUnit | None] = relationship(lazy="joined")


class CameraVendor(str, enum.Enum):
    """How Argus talks to a device: stream URL templates and probing."""

    hikvision = "hikvision"
    dahua = "dahua"
    uniview = "uniview"
    axis = "axis"
    vigi = "vigi"  # TP-Link VIGI
    reolink = "reolink"
    ezviz = "ezviz"
    dvrip = "dvrip"  # XMeye / Xiongmai cheap DVRs and cameras
    onvif = "onvif"  # any ONVIF camera; stream URLs come from the device
    rtsp = "rtsp"  # raw RTSP link
    http = "http"  # HTTP MJPEG / snapshot stream
    # Kept for rows written before stage 2; treated like `rtsp`.
    other = "other"


class DeviceKind(str, enum.Enum):
    camera = "camera"
    recorder = "recorder"  # NVR / DVR with several channels


class Direction(str, enum.Enum):
    entry = "entry"
    exit = "exit"
    none = "none"


class StreamQuality(str, enum.Enum):
    main = "main"
    sub = "sub"


class CredentialProfile(Base):
    """A login/password pair reused for many devices, e.g. one per site."""

    __tablename__ = "credential_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    password_enc: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    """Something Argus connects to: a camera or a recorder.

    Credentials live here, so changing a recorder's password updates all of
    its channels at once. Each channel shown on the wall is a `Camera`.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[DeviceKind] = mapped_column(_enum(DeviceKind), default=DeviceKind.camera)
    vendor: Mapped[CameraVendor] = mapped_column(_enum(CameraVendor))
    host: Mapped[str] = mapped_column(String(255), default="", index=True)
    rtsp_port: Mapped[int] = mapped_column(Integer, default=554)
    http_port: Mapped[int] = mapped_column(Integer, default=80)
    # Either a saved profile (shared by many devices) or the device's own pair.
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credential_profiles.id", ondelete="RESTRICT"), index=True
    )
    username: Mapped[str] = mapped_column(String(100), default="")
    password_enc: Mapped[str] = mapped_column(String(500), default="")
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_units.id", ondelete="RESTRICT"), index=True
    )

    model: Mapped[str] = mapped_column(String(200), default="")
    serial: Mapped[str] = mapped_column(String(100), default="", index=True)
    mac: Mapped[str] = mapped_column(String(32), default="", index=True)
    firmware: Mapped[str] = mapped_column(String(200), default="")

    # None until the first status check.
    online: Mapped[bool | None] = mapped_column(Boolean)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    org_unit: Mapped[OrgUnit] = relationship(lazy="joined")
    credential: Mapped[CredentialProfile | None] = relationship(lazy="joined")
    cameras: Mapped[list["Camera"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        order_by="Camera.channel",
        lazy="selectin",
    )


class Camera(Base):
    """One channel of a device, as shown on the wall."""

    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[int] = mapped_column(Integer, default=1)
    # Explicit stream links (without credentials). Filled from ONVIF, or set
    # by hand to override the vendor template; required for rtsp/http.
    rtsp_main: Mapped[str] = mapped_column(String(1000), default="")
    rtsp_sub: Mapped[str] = mapped_column(String(1000), default="")

    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_units.id", ondelete="RESTRICT"), index=True
    )
    face_recognition: Mapped[bool] = mapped_column(Boolean, default=False)
    direction: Mapped[Direction] = mapped_column(_enum(Direction), default=Direction.none)
    # [{"days": [1..7], "start": "HH:MM", "end": "HH:MM"}]; empty = around the clock.
    schedule: Mapped[list] = mapped_column(JSON, default=list)
    recognition_stream: Mapped[StreamQuality] = mapped_column(
        _enum(StreamQuality), default=StreamQuality.sub
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when "refresh channels" no longer finds this channel on the recorder.
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    org_unit: Mapped[OrgUnit] = relationship(lazy="joined")
    device: Mapped[Device] = relationship(back_populates="cameras", lazy="joined")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    personnel_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    position: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_units.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    org_unit: Mapped[OrgUnit] = relationship(lazy="joined")
    photos: Mapped[list["EmployeePhoto"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        order_by="EmployeePhoto.created_at",
        lazy="selectin",
    )


MAX_PHOTOS = 5


class EmployeePhoto(Base):
    __tablename__ = "employee_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    image_path: Mapped[str] = mapped_column(String(300))
    # float32 face embedding as raw bytes
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    employee: Mapped[Employee] = relationship(back_populates="photos")


class EventKind(str, enum.Enum):
    recognized = "recognized"
    unknown = "unknown"


class FaceEvent(Base):
    """A face seen by a recognition camera.

    Camera and employee names are copied at write time, so history stays
    readable after a camera or employee is renamed or removed.
    """

    __tablename__ = "face_events"
    __table_args__ = (Index("ix_face_events_camera_time", "camera_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[EventKind] = mapped_column(_enum(EventKind))
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL")
    )
    camera_name: Mapped[str] = mapped_column(String(200))
    # Camera's org path at the moment of the event, used to scope operators.
    org_path: Mapped[str] = mapped_column(String(140), index=True)
    direction: Mapped[Direction] = mapped_column(_enum(Direction))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    employee_name: Mapped[str] = mapped_column(String(200), default="")
    similarity: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Recognized: face crop. Unknown: full frame screenshot.
    image_path: Mapped[str] = mapped_column(String(300))
    # Unknown only: face crop and embedding, used by "add as employee".
    face_path: Mapped[str] = mapped_column(String(300), default="")
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)

    employee: Mapped[Employee | None] = relationship(lazy="joined")

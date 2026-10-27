"""devices, credential profiles; cameras become device channels

Each existing camera gets its own device carrying the connection fields
(vendor, host, port, credentials) that used to live on the camera.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _enum(*values, name):
    return sa.Enum(*values, name=name, native_enum=False, length=16)


VENDORS = (
    "hikvision", "dahua", "uniview", "axis", "vigi", "reolink", "ezviz",
    "dvrip", "onvif", "rtsp", "http", "other",
)


def upgrade() -> None:
    op.create_table(
        "credential_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_enc", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", _enum("camera", "recorder", name="devicekind"), nullable=False),
        sa.Column("vendor", _enum(*VENDORS, name="cameravendor"), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("rtsp_port", sa.Integer(), nullable=False),
        sa.Column("http_port", sa.Integer(), nullable=False),
        sa.Column(
            "credential_id", sa.Uuid(), sa.ForeignKey("credential_profiles.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_enc", sa.String(500), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("serial", sa.String(100), nullable=False),
        sa.Column("mac", sa.String(32), nullable=False),
        sa.Column("firmware", sa.String(200), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("credential_id", "org_unit_id", "host", "serial", "mac"):
        op.create_index(f"ix_devices_{col}", "devices", [col])

    with op.batch_alter_table("cameras") as batch:
        batch.add_column(sa.Column("device_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("missing", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Typed lightweight tables, so UUIDs and timestamps bind correctly on
    # both SQLite (development) and PostgreSQL.
    conn = op.get_bind()
    old_cameras = sa.table(
        "cameras",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("vendor", sa.String()),
        sa.column("host", sa.String()),
        sa.column("port", sa.Integer()),
        sa.column("username", sa.String()),
        sa.column("password_enc", sa.String()),
        sa.column("org_unit_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("device_id", sa.Uuid()),
    )
    devices = sa.table(
        "devices",
        sa.column("id", sa.Uuid()),
        sa.column("org_unit_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        *(sa.column(c, sa.String()) for c in (
            "name", "kind", "vendor", "host", "username", "password_enc", "model", "serial", "mac", "firmware",
        )),
        sa.column("rtsp_port", sa.Integer()),
        sa.column("http_port", sa.Integer()),
    )
    now = datetime.now(timezone.utc)
    for cam in conn.execute(sa.select(old_cameras)).mappings().all():
        device_id = uuid.uuid4()
        conn.execute(
            devices.insert().values(
                id=device_id,
                name=cam["name"],
                kind="camera",
                vendor="rtsp" if cam["vendor"] == "other" else cam["vendor"],
                host=cam["host"] or "",
                rtsp_port=cam["port"] or 554,
                http_port=80,
                username=cam["username"] or "",
                password_enc=cam["password_enc"] or "",
                org_unit_id=cam["org_unit_id"],
                model="",
                serial="",
                mac="",
                firmware="",
                created_at=cam["created_at"] or now,
                updated_at=now,
            )
        )
        conn.execute(
            old_cameras.update().where(old_cameras.c.id == cam["id"]).values(device_id=device_id)
        )

    with op.batch_alter_table("cameras") as batch:
        batch.alter_column("device_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_index("ix_cameras_device_id", ["device_id"])
        batch.create_foreign_key(
            "fk_cameras_device_id", "devices", ["device_id"], ["id"], ondelete="CASCADE"
        )
        for col in ("vendor", "host", "port", "username", "password_enc"):
            batch.drop_column(col)


def downgrade() -> None:
    raise NotImplementedError("stage 2 schema cannot be downgraded automatically")

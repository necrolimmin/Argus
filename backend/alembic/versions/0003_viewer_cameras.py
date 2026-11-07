"""cameras given to viewers

The role column is a plain string, so the new "viewer" role needs no change.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_cameras",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("camera_id", sa.Uuid(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_user_cameras_camera_id", "user_cameras", ["camera_id"])


def downgrade() -> None:
    op.drop_index("ix_user_cameras_camera_id", table_name="user_cameras")
    op.drop_table("user_cameras")

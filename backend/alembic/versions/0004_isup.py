"""Hikvision devices that connect by themselves (ISUP 5.0)

The vendor column is a plain string, so the new "isup" vendor needs no change.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("isup_id", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_devices_isup_id", ["isup_id"])


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("uq_devices_isup_id", type_="unique")
        batch.drop_column("isup_id")

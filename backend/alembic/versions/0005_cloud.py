"""Hik-Connect / EZVIZ cloud accounts

The vendor column is a plain string, so the new "cloud" vendor needs no change.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("login", sa.String(200), nullable=False),
        sa.Column("password_enc", sa.String(500), nullable=False, server_default=""),
        sa.Column("api_domain", sa.String(120), nullable=False, server_default=""),
        sa.Column("feature_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("session_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.String(64), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("cloud_account_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_devices_cloud_account_id", ["cloud_account_id"])
        batch.create_foreign_key(
            "fk_devices_cloud_account_id", "cloud_accounts", ["cloud_account_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("fk_devices_cloud_account_id", type_="foreignkey")
        batch.drop_index("ix_devices_cloud_account_id")
        batch.drop_column("cloud_account_id")
    op.drop_table("cloud_accounts")

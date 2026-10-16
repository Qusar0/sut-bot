"""stat daily (история автоотметки)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stat_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("scans", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("marked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lk_down", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_scan", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("stat_daily")

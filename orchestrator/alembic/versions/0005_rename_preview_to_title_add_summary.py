"""Rename preview to title, add summary to sessions

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("sessions", "preview", new_column_name="title")
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "summary")
    op.alter_column("sessions", "title", new_column_name="preview")

"""UUID schema — replace string PKs with UUIDs, add username to owners

Revision ID: 0001
Revises:
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop pre-existing tables from any previous schema
    op.execute("DROP TABLE IF EXISTS connectors CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS owners CASCADE")

    op.create_table(
        "owners",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("persona", sa.Text(), nullable=True),
        sa.Column("creed", sa.Text(), nullable=True),
        sa.Column("bond", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_owners_username"),
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("pulse", sa.Text(), nullable=True),
        sa.Column("pulse_config", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "connectors",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("instance_id", sa.String(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "instance_id"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("messages_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("connectors")
    op.drop_table("profiles")
    op.drop_table("owners")

"""Refine contacts schema: drop connector_id, add sources_json and vip

contacts.connector_id is removed entirely — routing is now derived at runtime
from the connector's declared channel type, not stored in contact data.
contacts.sources_json is added to track per-address provenance (Google, Apple, etc.).
personas.vip is added as a boolean flag for high-priority contacts.
named_channels.connector_id is renamed to via_connector (intrinsic: a named
channel IS tied to a specific connector workspace).

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # personas: add vip flag
    with op.batch_alter_table("personas") as batch_op:
        batch_op.add_column(sa.Column("vip", sa.Integer(), nullable=False, server_default="0"))

    # contacts: drop connector_id, add sources_json
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("connector_id")
        batch_op.add_column(
            sa.Column("sources_json", sa.Text(), nullable=False, server_default="[]")
        )

    # named_channels: rename connector_id → via_connector
    with op.batch_alter_table("named_channels") as batch_op:
        batch_op.alter_column("connector_id", new_column_name="via_connector")


def downgrade() -> None:
    with op.batch_alter_table("named_channels") as batch_op:
        batch_op.alter_column("via_connector", new_column_name="connector_id")

    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("sources_json")
        batch_op.add_column(
            sa.Column("connector_id", sa.String(), nullable=False, server_default="")
        )

    with op.batch_alter_table("personas") as batch_op:
        batch_op.drop_column("vip")

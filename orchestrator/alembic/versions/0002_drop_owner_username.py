"""Drop username column from owners — UUID is the sole identifier

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_owners_username", "owners", type_="unique")
    op.drop_column("owners", "username")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column("owners", sa.Column("username", sa.String(), nullable=True))
    op.execute("UPDATE owners SET username = id WHERE username IS NULL")
    op.alter_column("owners", "username", nullable=False)
    op.create_unique_constraint("uq_owners_username", "owners", ["username"])

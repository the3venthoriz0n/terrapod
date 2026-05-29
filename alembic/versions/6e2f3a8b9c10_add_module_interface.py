"""add_module_interface

Revision ID: 6e2f3a8b9c10
Revises: 5a173d4b4e20
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "6e2f3a8b9c10"
down_revision: str | None = "5a173d4b4e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registry_module_versions", sa.Column("inputs", JSONB, nullable=True))
    op.add_column(
        "registry_module_versions", sa.Column("outputs", JSONB, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("registry_module_versions", "outputs")
    op.drop_column("registry_module_versions", "inputs")

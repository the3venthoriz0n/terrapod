"""Add state_mode to workspaces, runs, and autodiscovery_rules.

Revision ID: a1b2c3d4e5f6
Revises: 42266b856e8e
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "42266b856e8e"


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("state_mode", sa.String(20), nullable=False, server_default="managed"),
    )
    op.add_column(
        "runs",
        sa.Column("state_mode", sa.String(20), nullable=False, server_default="managed"),
    )
    op.add_column(
        "autodiscovery_rules",
        sa.Column("state_mode", sa.String(20), nullable=False, server_default="managed"),
    )


def downgrade() -> None:
    op.drop_column("autodiscovery_rules", "state_mode")
    op.drop_column("runs", "state_mode")
    op.drop_column("workspaces", "state_mode")

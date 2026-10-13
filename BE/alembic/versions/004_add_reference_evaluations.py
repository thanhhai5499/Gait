"""Add reference_evaluations JSON column to gait_analyses

Revision ID: 004_add_reference_evaluations
Revises: 003_add_user_profile_fields
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_add_reference_evaluations"
down_revision = "003_add_user_profile_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gait_analyses",
        sa.Column("reference_evaluations", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gait_analyses", "reference_evaluations")

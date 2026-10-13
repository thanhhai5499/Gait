"""Add score_breakdown to gait_analyses

Revision ID: 011_add_score_breakdown
Revises: 010_add_fsr_double_support
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '011_add_score_breakdown'
down_revision = '010_add_fsr_double_support'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gait_analyses', sa.Column('score_breakdown', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('gait_analyses', 'score_breakdown')

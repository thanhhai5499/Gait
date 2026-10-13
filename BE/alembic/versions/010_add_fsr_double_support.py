"""Add fsr_stats and double_support to gait_analyses

Revision ID: 010_add_fsr_double_support
Revises: 009_update_sensor_fields
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = '010_add_fsr_double_support'
down_revision = '009_update_sensor_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gait_analyses', sa.Column('fsr_stats',       sa.JSON(), nullable=True))
    op.add_column('gait_analyses', sa.Column('double_support',  sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('gait_analyses', 'double_support')
    op.drop_column('gait_analyses', 'fsr_stats')

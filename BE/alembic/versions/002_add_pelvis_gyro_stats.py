"""add pelvis_gyro_stats

Revision ID: 002_add_pelvis_gyro_stats
Revises: 000_init
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision = '002_add_pelvis_gyro_stats'
down_revision = '000_init'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gait_analyses', sa.Column('pelvis_gyro_stats', JSON, nullable=True))


def downgrade() -> None:
    op.drop_column('gait_analyses', 'pelvis_gyro_stats')

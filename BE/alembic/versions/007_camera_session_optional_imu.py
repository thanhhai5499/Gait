"""Make camera_sessions.measurement_session_id nullable

Revision ID: 007_camera_session_optional_imu
Revises: 006_add_camera_sessions
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = '007_camera_session_optional_imu'
down_revision = '006_add_camera_sessions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('camera_sessions') as batch_op:
        batch_op.alter_column(
            'measurement_session_id',
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('camera_sessions') as batch_op:
        batch_op.alter_column(
            'measurement_session_id',
            existing_type=sa.Integer(),
            nullable=False,
        )

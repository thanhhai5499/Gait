"""Drop measurement_session_id from camera_sessions

Revision ID: 008_drop_camera_measurement_session_id
Revises: 007_camera_session_optional_imu
"""
from alembic import op
import sqlalchemy as sa

revision = '008_drop_camera_meas_sid'
down_revision = '007_camera_session_optional_imu'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_camera_sessions_measurement_session_id', table_name='camera_sessions')
    op.drop_constraint('camera_sessions_measurement_session_id_fkey', 'camera_sessions', type_='foreignkey')
    op.drop_column('camera_sessions', 'measurement_session_id')


def downgrade() -> None:
    op.add_column('camera_sessions',
        sa.Column('measurement_session_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_camera_sessions_measurement_session_id',
        'camera_sessions',
        'measurement_sessions',
        ['measurement_session_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_camera_sessions_measurement_session_id',
        'camera_sessions',
        ['measurement_session_id'],
    )

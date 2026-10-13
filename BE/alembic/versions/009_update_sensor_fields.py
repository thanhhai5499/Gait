"""Update sensor_readings: dual FSR, rename accel/gyro, add magnetometer

Revision ID: 009_update_sensor_fields
Revises: 008_drop_camera_meas_sid
Create Date: 2026-06-12

Changes:
  sensor_readings:
    - rename left_force  → left_force_1,  add left_force_2
    - rename right_force → right_force_1, add right_force_2
    - rename pelvis_accel_x/y/z → accel_x/y/z
    - rename pelvis_gyro_x/y/z  → gyro_x/y/z
    - add magn_x, magn_y, magn_z

  gait_analyses:
    - add magn_stats (JSON)
"""
from alembic import op
import sqlalchemy as sa

revision = '009_update_sensor_fields'
down_revision = '008_drop_camera_meas_sid'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sensor_readings ──────────────────────────────────────────────────────

    # Force: rename left_force → left_force_1, add left_force_2
    op.alter_column('sensor_readings', 'left_force',  new_column_name='left_force_1')
    op.alter_column('sensor_readings', 'right_force', new_column_name='right_force_1')
    op.add_column('sensor_readings', sa.Column('left_force_2',  sa.Float(), nullable=True))
    op.add_column('sensor_readings', sa.Column('right_force_2', sa.Float(), nullable=True))

    # Accelerometer: rename pelvis_accel_* → accel_*
    op.alter_column('sensor_readings', 'pelvis_accel_x', new_column_name='accel_x')
    op.alter_column('sensor_readings', 'pelvis_accel_y', new_column_name='accel_y')
    op.alter_column('sensor_readings', 'pelvis_accel_z', new_column_name='accel_z')

    # Gyroscope: rename pelvis_gyro_* → gyro_*
    op.alter_column('sensor_readings', 'pelvis_gyro_x', new_column_name='gyro_x')
    op.alter_column('sensor_readings', 'pelvis_gyro_y', new_column_name='gyro_y')
    op.alter_column('sensor_readings', 'pelvis_gyro_z', new_column_name='gyro_z')

    # Magnetometer: new columns
    op.add_column('sensor_readings', sa.Column('magn_x', sa.Float(), nullable=True))
    op.add_column('sensor_readings', sa.Column('magn_y', sa.Float(), nullable=True))
    op.add_column('sensor_readings', sa.Column('magn_z', sa.Float(), nullable=True))

    # ── gait_analyses ─────────────────────────────────────────────────────────
    op.add_column('gait_analyses', sa.Column('magn_stats', sa.JSON(), nullable=True))


def downgrade() -> None:
    # gait_analyses
    op.drop_column('gait_analyses', 'magn_stats')

    # sensor_readings — magnetometer
    op.drop_column('sensor_readings', 'magn_z')
    op.drop_column('sensor_readings', 'magn_y')
    op.drop_column('sensor_readings', 'magn_x')

    # gyroscope
    op.alter_column('sensor_readings', 'gyro_x', new_column_name='pelvis_gyro_x')
    op.alter_column('sensor_readings', 'gyro_y', new_column_name='pelvis_gyro_y')
    op.alter_column('sensor_readings', 'gyro_z', new_column_name='pelvis_gyro_z')

    # accelerometer
    op.alter_column('sensor_readings', 'accel_x', new_column_name='pelvis_accel_x')
    op.alter_column('sensor_readings', 'accel_y', new_column_name='pelvis_accel_y')
    op.alter_column('sensor_readings', 'accel_z', new_column_name='pelvis_accel_z')

    # force
    op.drop_column('sensor_readings', 'right_force_2')
    op.drop_column('sensor_readings', 'left_force_2')
    op.alter_column('sensor_readings', 'right_force_1', new_column_name='right_force')
    op.alter_column('sensor_readings', 'left_force_1',  new_column_name='left_force')

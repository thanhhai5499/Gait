"""Initial schema creation

Revision ID: 000_init
Revises:
Create Date: 2026-05-27

Creates all tables from scratch based on models.py
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "000_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("hashed_password", sa.String(length=256), nullable=True),
        sa.Column("role", sa.Enum("admin", "user", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("auth_provider", sa.Enum("local", "google", name="authprovider"), nullable=False),
        sa.Column("google_id", sa.String(length=128), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # Create measurement_sessions table
    op.create_table(
        "measurement_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("idle", "recording", "paused", "completed", name="sessionstatus"), nullable=False),
        sa.Column("com_port", sa.String(length=32), nullable=True),
        sa.Column("baud_rate", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("walk_distance_m", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_measurement_sessions_id"), "measurement_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_measurement_sessions_session_code"), "measurement_sessions", ["session_code"], unique=True)

    # Create sensor_readings table
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("timestamp_ms", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.Column("left_hip", sa.Float(), nullable=True),
        sa.Column("left_knee", sa.Float(), nullable=True),
        sa.Column("right_hip", sa.Float(), nullable=True),
        sa.Column("right_knee", sa.Float(), nullable=True),
        sa.Column("left_force", sa.Float(), nullable=True),
        sa.Column("right_force", sa.Float(), nullable=True),
        sa.Column("pelvis_accel_x", sa.Float(), nullable=True),
        sa.Column("pelvis_accel_y", sa.Float(), nullable=True),
        sa.Column("pelvis_accel_z", sa.Float(), nullable=True),
        sa.Column("pelvis_gyro_x", sa.Float(), nullable=True),
        sa.Column("pelvis_gyro_y", sa.Float(), nullable=True),
        sa.Column("pelvis_gyro_z", sa.Float(), nullable=True),
        sa.Column("phase_left", sa.Enum("stance", "swing", "unknown", name="gaitphase"), nullable=True),
        sa.Column("phase_right", sa.Enum("stance", "swing", "unknown", name="gaitphase"), nullable=True),
        sa.Column("signal_quality", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["measurement_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sensor_readings_session_id"), "sensor_readings", ["session_id"], unique=False)

    # Create gait_analyses table
    op.create_table(
        "gait_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("left_hip_stats", sa.JSON(), nullable=True),
        sa.Column("left_knee_stats", sa.JSON(), nullable=True),
        sa.Column("right_hip_stats", sa.JSON(), nullable=True),
        sa.Column("right_knee_stats", sa.JSON(), nullable=True),
        sa.Column("left_gait_cycle", sa.JSON(), nullable=True),
        sa.Column("right_gait_cycle", sa.JSON(), nullable=True),
        sa.Column("symmetry_index_hip", sa.Float(), nullable=True),
        sa.Column("symmetry_index_knee", sa.Float(), nullable=True),
        sa.Column("pelvis_sway_stats", sa.JSON(), nullable=True),
        sa.Column("gait_score", sa.Float(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["measurement_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("gait_analyses")
    op.drop_table("sensor_readings")
    op.drop_table("measurement_sessions")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

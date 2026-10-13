"""Add camera_sessions table

Revision ID: 006_add_camera_sessions
Revises: 005_add_refresh_tokens
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = '006_add_camera_sessions'
down_revision = '005_add_refresh_tokens'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'camera_sessions',
        sa.Column('id',                     sa.Integer(),  nullable=False),
        sa.Column('measurement_session_id', sa.Integer(),  nullable=False),
        sa.Column('user_id',                sa.Integer(),  nullable=False),
        sa.Column('recorded_at',            sa.DateTime(), nullable=False),
        sa.Column('duration_s',             sa.Float(),    nullable=True),
        sa.Column('frames',                 sa.Integer(),  nullable=True),
        sa.Column('cameras_used',           sa.Integer(),  server_default='1', nullable=False),
        sa.Column('analysis',               sa.JSON(),     nullable=True),
        sa.Column('notes',                  sa.Text(),     nullable=True),
        sa.Column('created_at',             sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['measurement_session_id'], ['measurement_sessions.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_camera_sessions_id',                     'camera_sessions', ['id'])
    op.create_index('ix_camera_sessions_user_id',                'camera_sessions', ['user_id'])
    op.create_index('ix_camera_sessions_measurement_session_id', 'camera_sessions', ['measurement_session_id'])


def downgrade() -> None:
    op.drop_index('ix_camera_sessions_measurement_session_id', table_name='camera_sessions')
    op.drop_index('ix_camera_sessions_user_id',                table_name='camera_sessions')
    op.drop_index('ix_camera_sessions_id',                     table_name='camera_sessions')
    op.drop_table('camera_sessions')

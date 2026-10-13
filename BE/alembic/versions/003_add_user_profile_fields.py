"""Add age, sex, weight_kg, height_cm to users table

Revision ID: 003_add_user_profile_fields
Revises: 002_add_pelvis_gyro_stats
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "003_add_user_profile_fields"
down_revision = "002_add_pelvis_gyro_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sex_enum = sa.Enum("male", "female", name="sex")
    sex_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("users", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("sex", sa.Enum("male", "female", name="sex"), nullable=True))
    op.add_column("users", sa.Column("weight_kg", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("height_cm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "height_cm")
    op.drop_column("users", "weight_kg")
    op.drop_column("users", "sex")
    op.drop_column("users", "age")
    op.execute("DROP TYPE IF EXISTS sex")

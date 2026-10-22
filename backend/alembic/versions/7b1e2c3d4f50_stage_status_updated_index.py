"""index stage_status(stage, updated_at) for live progress queries

Revision ID: 7b1e2c3d4f50
Revises: 6c569c11c2cb
"""
from alembic import op

revision = "7b1e2c3d4f50"
down_revision = "6c569c11c2cb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_stage_status_stage_updated", "stage_status", ["stage", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_stage_status_stage_updated", table_name="stage_status")

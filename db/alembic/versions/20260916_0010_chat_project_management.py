"""add ordering and soft deletion to Chat projects

Revision ID: 0010_chat_project_management
Revises: 0009_plugin_chat
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_chat_project_management"
down_revision: Union[str, Sequence[str], None] = "0009_plugin_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_projects",
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("chat_projects", sa.Column("deleted_at", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("chat_projects", "deleted_at")
    op.drop_column("chat_projects", "sort_order")

"""track prompt-cache tokens and estimated savings in usage

Revision ID: 0011_usage_cache_tokens
Revises: 0010_chat_project_management
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_usage_cache_tokens"
down_revision: Union[str, Sequence[str], None] = "0010_chat_project_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Nullable on purpose: old rows were never measured, so NULL (not 0) keeps
    # them out of the cache percentage.
    op.add_column("usage", sa.Column("cached_tokens", sa.Integer, nullable=True))
    op.add_column("usage", sa.Column("saved_usd", sa.Float, nullable=True))

def downgrade() -> None:
    op.drop_column("usage", "saved_usd")
    op.drop_column("usage", "cached_tokens")

"""add persistent plugin creator chat

Revision ID: 0009_plugin_chat
Revises: 0008_plugin_installed_deps
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_plugin_chat"
down_revision: Union[str, Sequence[str], None] = "0008_plugin_installed_deps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_projects",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False, server_default="plugin"),
        sa.Column("plugin_id", sa.Text),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("workspace_path", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
    )
    op.create_index("idx_chat_projects_updated", "chat_projects", ["updated_at"])

    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("project_id", sa.Text, sa.ForeignKey("chat_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default="Nova conversa"),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("reasoning", sa.Text, nullable=False, server_default=""),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("compacted_through_id", sa.Integer),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
    )
    op.create_index(
        "idx_chat_conversations_project", "chat_conversations", ["project_id", "updated_at"]
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Text, sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("kind", sa.Text, nullable=False, server_default="message"),
        sa.Column("metadata", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_index(
        "idx_chat_messages_conversation", "chat_messages", ["conversation_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("idx_chat_messages_conversation", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("idx_chat_conversations_project", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    op.drop_index("idx_chat_projects_updated", table_name="chat_projects")
    op.drop_table("chat_projects")

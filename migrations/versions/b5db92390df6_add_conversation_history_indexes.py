"""增加单聊历史查询索引

Revision ID: b5db92390df6
Revises: e5f06ff274b9
Create Date: 2026-09-03 19:57:51.840567

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5db92390df6"
down_revision: str | Sequence[str] | None = "e5f06ff274b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """使用有向复合索引支持双向单聊历史查询。"""
    op.drop_index("ix_messages_recipient_created_message", table_name="messages")
    op.create_index(
        "ix_messages_sender_recipient_created_message",
        "messages",
        ["sender_id", "recipient_id", "created_at", "message_id"],
        unique=False,
    )


def downgrade() -> None:
    """恢复 Issue 14 的收件人历史索引。"""
    op.drop_index(
        "ix_messages_sender_recipient_created_message",
        table_name="messages",
    )
    op.create_index(
        "ix_messages_recipient_created_message",
        "messages",
        ["recipient_id", "created_at", "message_id"],
        unique=False,
    )

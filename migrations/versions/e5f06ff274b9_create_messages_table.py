"""创建消息表

Revision ID: e5f06ff274b9
Revises:
Create Date: 2026-09-03 19:12:35.431273

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f06ff274b9"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建消息表、数据约束和收件箱查询索引。"""
    op.create_table(
        "messages",
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("client_message_id", sa.String(length=36), nullable=False),
        sa.Column("sender_id", sa.Text(), nullable=False),
        sa.Column("recipient_id", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(client_message_id) = 36",
            name="ck_messages_client_message_id_length",
        ),
        sa.CheckConstraint(
            "length(message_id) = 36",
            name="ck_messages_message_id_length",
        ),
        sa.CheckConstraint(
            "length(trim(content)) BETWEEN 1 AND 2000",
            name="ck_messages_content_length",
        ),
        sa.CheckConstraint(
            "length(trim(recipient_id)) > 0",
            name="ck_messages_recipient_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(sender_id)) > 0",
            name="ck_messages_sender_id_not_blank",
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint(
            "sender_id",
            "client_message_id",
            name="uq_messages_sender_client_message",
        ),
    )
    op.create_index(
        "ix_messages_recipient_created_message",
        "messages",
        ["recipient_id", "created_at", "message_id"],
        unique=False,
    )


def downgrade() -> None:
    """删除消息索引和消息表。"""
    op.drop_index("ix_messages_recipient_created_message", table_name="messages")
    op.drop_table("messages")

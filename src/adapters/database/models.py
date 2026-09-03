"""
消息持久化 ORM 映射

ORM 类型只描述数据库结构，不承担领域行为。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.domain.message import MAX_MESSAGE_CONTENT_LENGTH


class DatabaseBase(DeclarativeBase):
    """数据库 ORM 映射基类。"""


class MessageRecord(DatabaseBase):
    """聊天消息在关系数据库中的持久化记录。"""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "sender_id",
            "client_message_id",
            name="uq_messages_sender_client_message",
        ),
        CheckConstraint(
            "length(message_id) = 36",
            name="ck_messages_message_id_length",
        ),
        CheckConstraint(
            "length(client_message_id) = 36",
            name="ck_messages_client_message_id_length",
        ),
        CheckConstraint(
            "length(trim(sender_id)) > 0",
            name="ck_messages_sender_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(recipient_id)) > 0",
            name="ck_messages_recipient_id_not_blank",
        ),
        CheckConstraint(
            f"length(trim(content)) BETWEEN 1 AND {MAX_MESSAGE_CONTENT_LENGTH}",
            name="ck_messages_content_length",
        ),
        Index(
            "ix_messages_sender_recipient_created_message",
            "sender_id",
            "recipient_id",
            "created_at",
            "message_id",
        ),
    )

    messageId: Mapped[str] = mapped_column(
        "message_id",
        String(36),
        primary_key=True,
    )
    clientMessageId: Mapped[str] = mapped_column(
        "client_message_id",
        String(36),
        nullable=False,
    )
    senderId: Mapped[str] = mapped_column("sender_id", Text, nullable=False)
    recipientId: Mapped[str] = mapped_column("recipient_id", Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
    )

"""
消息持久化 ORM 映射

ORM 类型只描述数据库结构，不承担领域行为。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.domain.message import MAX_MESSAGE_CONTENT_LENGTH
from src.domain.user import MAX_USERNAME_LENGTH, MIN_USERNAME_LENGTH


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
            "ix_messages_conversation_created_message",
            "conversation_id",
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
    conversationId: Mapped[str] = mapped_column(
        "conversation_id",
        ForeignKey("conversations.conversation_id", ondelete="RESTRICT"),
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


class UserRecord(DatabaseBase):
    """认证用户在关系数据库中的持久化记录。"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "length(user_id) = 36",
            name="ck_users_user_id_length",
        ),
        CheckConstraint(
            f"length(username) BETWEEN {MIN_USERNAME_LENGTH} AND {MAX_USERNAME_LENGTH}",
            name="ck_users_username_length",
        ),
        CheckConstraint(
            "username = lower(trim(username))",
            name="ck_users_username_normalized",
        ),
        CheckConstraint(
            "length(trim(password_hash)) > 0",
            name="ck_users_password_hash_not_blank",
        ),
        UniqueConstraint("username", name="uq_users_username"),
    )

    userId: Mapped[str] = mapped_column(
        "user_id",
        String(36),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(
        String(MAX_USERNAME_LENGTH),
        nullable=False,
    )
    passwordHash: Mapped[str] = mapped_column(
        "password_hash",
        Text,
        nullable=False,
    )
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
    )


class ConversationRecord(DatabaseBase):
    """一对一会话聚合根的持久化记录。"""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "length(conversation_id) = 36",
            name="ck_conversations_id_length",
        ),
        CheckConstraint(
            "length(trim(member_pair_key)) > 2",
            name="ck_conversations_member_pair_key_not_blank",
        ),
        UniqueConstraint(
            "member_pair_key",
            name="uq_conversations_member_pair_key",
        ),
    )

    conversationId: Mapped[str] = mapped_column(
        "conversation_id",
        String(36),
        primary_key=True,
    )
    memberPairKey: Mapped[str] = mapped_column(
        "member_pair_key",
        Text,
        nullable=False,
    )
    createdAt: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
    )
    members: Mapped[list["ConversationMemberRecord"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ConversationMemberRecord.memberPosition",
    )


class ConversationMemberRecord(DatabaseBase):
    """会话成员关联记录，不承载在线状态或成员角色。"""

    __tablename__ = "conversation_members"
    __table_args__ = (
        CheckConstraint(
            "member_position IN (1, 2)",
            name="ck_conversation_members_position",
        ),
        UniqueConstraint(
            "conversation_id",
            "member_position",
            name="uq_conversation_members_position",
        ),
        CheckConstraint(
            "(delivered_created_at IS NULL) = (delivered_message_id IS NULL)",
            name="ck_conversation_members_delivered_pair",
        ),
        CheckConstraint(
            "(read_created_at IS NULL) = (read_message_id IS NULL)",
            name="ck_conversation_members_read_pair",
        ),
    )

    conversationId: Mapped[str] = mapped_column(
        "conversation_id",
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    userId: Mapped[str] = mapped_column(
        "user_id",
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    memberPosition: Mapped[int] = mapped_column(
        "member_position",
        Integer,
        nullable=False,
    )
    deliveredCreatedAt: Mapped[datetime | None] = mapped_column(
        "delivered_created_at",
        DateTime(timezone=True),
        nullable=True,
    )
    deliveredMessageId: Mapped[str | None] = mapped_column(
        "delivered_message_id",
        ForeignKey("messages.message_id", ondelete="RESTRICT"),
        nullable=True,
    )
    readCreatedAt: Mapped[datetime | None] = mapped_column(
        "read_created_at",
        DateTime(timezone=True),
        nullable=True,
    )
    readMessageId: Mapped[str | None] = mapped_column(
        "read_message_id",
        ForeignKey("messages.message_id", ondelete="RESTRICT"),
        nullable=True,
    )
    conversation: Mapped[ConversationRecord] = relationship(back_populates="members")

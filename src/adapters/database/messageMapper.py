"""领域消息与 SQLAlchemy 消息记录之间的显式转换。"""

from datetime import datetime, timezone
from uuid import UUID

from src.adapters.database.models import MessageRecord
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    MessageContent,
    MessageId,
    UserId,
)


def toMessageRecord(message: ChatMessage) -> MessageRecord:
    """将领域消息转换为只负责持久化的 ORM 记录。"""
    return MessageRecord(
        messageId=str(message.message_id),
        clientMessageId=str(message.client_message_id),
        conversationId=str(message.conversation_id),
        senderId=str(message.sender_id),
        recipientId=str(message.recipient_id),
        content=str(message.content),
        createdAt=message.created_at,
    )


def toDomainMessage(record: MessageRecord) -> ChatMessage:
    """将 ORM 记录转换为重新验证不变量的领域消息。"""
    return ChatMessage(
        message_id=MessageId(UUID(record.messageId)),
        client_message_id=ClientMessageId(UUID(record.clientMessageId)),
        conversation_id=ConversationId(UUID(record.conversationId)),
        sender_id=UserId(record.senderId),
        recipient_id=UserId(record.recipientId),
        content=MessageContent(record.content),
        created_at=normalizeDatabaseDatetime(record.createdAt),
    )


def normalizeDatabaseDatetime(value: datetime) -> datetime:
    """兼容 SQLite 无时区值，并把所有数据库时间统一为 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

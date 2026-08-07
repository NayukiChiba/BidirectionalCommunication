"""消息领域公开接口。"""

from domain.exceptions import (
    DomainError,
    InvalidChatMessage,
    InvalidClientMessageId,
    InvalidMessageContent,
    InvalidMessageCreatedAt,
    InvalidMessageId,
    InvalidUserId,
)
from domain.message import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
    create_chat_message,
)

__all__ = [
    "ChatMessage",
    "ClientMessageId",
    "DomainError",
    "InvalidChatMessage",
    "InvalidClientMessageId",
    "InvalidMessageContent",
    "InvalidMessageCreatedAt",
    "InvalidMessageId",
    "InvalidUserId",
    "MessageContent",
    "MessageId",
    "UserId",
    "create_chat_message",
]

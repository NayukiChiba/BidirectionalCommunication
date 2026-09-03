"""消息领域公开接口。"""

from .exceptions import (
    DomainError,
    InvalidChatMessage,
    InvalidClientMessageId,
    InvalidMessageContent,
    InvalidMessageCreatedAt,
    InvalidMessageId,
    InvalidUserId,
)
from .message import (
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

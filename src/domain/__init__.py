"""用户、会话与消息领域公开接口。"""

from src.domain.conversation import (
    Conversation,
    ConversationId,
    createConversation,
)
from src.domain.delivery import ConversationProgress, MessagePosition
from src.domain.exceptions import (
    ConversationMemberRequired,
    DomainError,
    InvalidChatMessage,
    InvalidClientMessageId,
    InvalidConversation,
    InvalidConversationId,
    InvalidMessageContent,
    InvalidMessageCreatedAt,
    InvalidMessageId,
    InvalidMessagePosition,
    InvalidPasswordHash,
    InvalidUser,
    InvalidUserId,
    InvalidUsername,
    ReadPositionBeyondDelivery,
)
from src.domain.identifiers import UserId
from src.domain.message import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    create_chat_message,
)
from src.domain.user import PasswordHash, User, Username, createUser

__all__ = [
    "ChatMessage",
    "ClientMessageId",
    "Conversation",
    "ConversationId",
    "ConversationMemberRequired",
    "ConversationProgress",
    "DomainError",
    "InvalidChatMessage",
    "InvalidConversation",
    "InvalidConversationId",
    "InvalidClientMessageId",
    "InvalidMessageContent",
    "InvalidMessageCreatedAt",
    "InvalidMessageId",
    "InvalidMessagePosition",
    "InvalidPasswordHash",
    "InvalidUser",
    "InvalidUserId",
    "InvalidUsername",
    "MessageContent",
    "MessageId",
    "MessagePosition",
    "PasswordHash",
    "ReadPositionBeyondDelivery",
    "User",
    "UserId",
    "Username",
    "createConversation",
    "createUser",
    "create_chat_message",
]

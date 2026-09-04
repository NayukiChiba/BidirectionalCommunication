"""用户、会话与消息领域公开接口。"""

from src.domain.conversation import (
    Conversation,
    ConversationId,
    createConversation,
)
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
    InvalidPasswordHash,
    InvalidUser,
    InvalidUserId,
    InvalidUsername,
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
    "DomainError",
    "InvalidChatMessage",
    "InvalidConversation",
    "InvalidConversationId",
    "InvalidClientMessageId",
    "InvalidMessageContent",
    "InvalidMessageCreatedAt",
    "InvalidMessageId",
    "InvalidPasswordHash",
    "InvalidUser",
    "InvalidUserId",
    "InvalidUsername",
    "MessageContent",
    "MessageId",
    "PasswordHash",
    "User",
    "UserId",
    "Username",
    "createConversation",
    "createUser",
    "create_chat_message",
]

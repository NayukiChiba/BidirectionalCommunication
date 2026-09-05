"""消息存储端口的内存适配器。"""

from src.application.models import MessageCursor
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    MessageId,
    UserId,
)


class InMemoryMessageRepository:
    """在当前进程内按服务端消息标识保存消息。"""

    def __init__(
        self,
        messages: dict[MessageId, ChatMessage] | None = None,
    ) -> None:
        """创建空存储或使用工作单元提供的消息字典。"""
        self._messages = messages if messages is not None else {}

    async def add(self, message: ChatMessage) -> None:
        """保存消息，并以消息的领域身份保证存储项唯一。"""
        self._messages[message.message_id] = message

    async def getByClientMessageId(
        self,
        senderId: UserId,
        clientMessageId: ClientMessageId,
    ) -> ChatMessage | None:
        """按发送者和客户端幂等键返回原消息。"""
        return next(
            (
                message
                for message in self._messages.values()
                if message.sender_id == senderId
                and message.client_message_id == clientMessageId
            ),
            None,
        )

    async def getById(self, messageId: MessageId) -> ChatMessage | None:
        """按服务端消息 ID 返回消息。"""
        return self._messages.get(messageId)

    async def listByConversation(
        self,
        conversationId: ConversationId,
        *,
        cursor: MessageCursor | None,
        limit: int,
    ) -> tuple[ChatMessage, ...]:
        """按创建时间和消息 ID 正向查询一个会话中的消息。"""
        messages = [
            message
            for message in self._messages.values()
            if message.conversation_id == conversationId
        ]
        messages.sort(key=lambda message: (message.created_at, str(message.message_id)))
        if cursor is not None:
            cursorKey = (cursor.created_at, str(cursor.message_id))
            messages = [
                message
                for message in messages
                if (message.created_at, str(message.message_id)) > cursorKey
            ]
        return tuple(messages[:limit])

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        """返回当前已保存消息的只读快照。"""
        return tuple(self._messages.values())

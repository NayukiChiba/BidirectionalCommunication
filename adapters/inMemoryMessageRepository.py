"""消息存储端口的内存适配器。"""

from domain import ChatMessage, MessageId


class InMemoryMessageRepository:
    """在当前进程内按服务端消息标识保存消息。"""

    def __init__(self) -> None:
        """创建空的内存消息存储。"""
        self._messages: dict[MessageId, ChatMessage] = {}

    def add(self, message: ChatMessage) -> None:
        """保存消息，并以消息的领域身份保证存储项唯一。"""
        self._messages[message.message_id] = message

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        """返回当前已保存消息的只读快照。"""
        return tuple(self._messages.values())

"""纯 Python 消息领域模型。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .exceptions import (
    InvalidChatMessage,
    InvalidClientMessageId,
    InvalidMessageContent,
    InvalidMessageCreatedAt,
    InvalidMessageId,
    InvalidUserId,
)

MAX_MESSAGE_CONTENT_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class UserId:
    """经过规范化的用户标识值对象。"""

    value: str

    def __post_init__(self) -> None:
        """验证并规范化用户标识。"""
        if not isinstance(self.value, str):
            raise InvalidUserId("用户标识必须是字符串")

        normalized_value = self.value.strip()
        if not normalized_value:
            raise InvalidUserId("用户标识不能为空")

        object.__setattr__(self, "value", normalized_value)

    def __str__(self) -> str:
        """返回可用于外层转换的文本值。"""
        return self.value


@dataclass(frozen=True, slots=True)
class MessageId:
    """服务端消息标识值对象。"""

    value: UUID

    def __post_init__(self) -> None:
        """验证服务端消息标识。"""
        if not isinstance(self.value, UUID):
            raise InvalidMessageId("服务端消息标识必须是 UUID")

    @classmethod
    def generate(cls) -> "MessageId":
        """生成新的服务端消息标识。"""
        return cls(uuid4())

    def __str__(self) -> str:
        """返回可用于外层转换的文本值。"""
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ClientMessageId:
    """客户端消息关联标识值对象。"""

    value: UUID

    def __post_init__(self) -> None:
        """验证客户端消息标识。"""
        if not isinstance(self.value, UUID):
            raise InvalidClientMessageId("客户端消息标识必须是 UUID")

    def __str__(self) -> str:
        """返回可用于外层转换的文本值。"""
        return str(self.value)


@dataclass(frozen=True, slots=True)
class MessageContent:
    """非空且长度受限的消息内容值对象。"""

    value: str

    def __post_init__(self) -> None:
        """验证并规范化消息内容。"""
        if not isinstance(self.value, str):
            raise InvalidMessageContent("消息内容必须是字符串")

        normalized_value = self.value.strip()
        if not normalized_value:
            raise InvalidMessageContent("消息内容不能为空")
        if len(normalized_value) > MAX_MESSAGE_CONTENT_LENGTH:
            raise InvalidMessageContent(
                f"消息内容不能超过 {MAX_MESSAGE_CONTENT_LENGTH} 个字符"
            )

        object.__setattr__(self, "value", normalized_value)

    def __str__(self) -> str:
        """返回可用于外层转换的文本值。"""
        return self.value


@dataclass(frozen=True, eq=False, slots=True)
class ChatMessage:
    """通过服务端消息标识维持身份的聊天消息实体。"""

    message_id: MessageId
    client_message_id: ClientMessageId
    sender_id: UserId
    recipient_id: UserId
    content: MessageContent
    created_at: datetime

    def __post_init__(self) -> None:
        """验证组合对象并统一消息创建时间为 UTC。"""
        expected_types = {
            "message_id": (self.message_id, MessageId),
            "client_message_id": (self.client_message_id, ClientMessageId),
            "sender_id": (self.sender_id, UserId),
            "recipient_id": (self.recipient_id, UserId),
            "content": (self.content, MessageContent),
        }
        for field_name, (field_value, expected_type) in expected_types.items():
            if not isinstance(field_value, expected_type):
                raise InvalidChatMessage(
                    f"{field_name} 必须是 {expected_type.__name__}"
                )

        if not isinstance(self.created_at, datetime):
            raise InvalidMessageCreatedAt("消息创建时间必须是 datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidMessageCreatedAt("消息创建时间必须包含时区")

        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )

    def __eq__(self, other: object) -> bool:
        """通过服务端消息标识判断是否为同一实体。"""
        if not isinstance(other, ChatMessage):
            return False
        return self.message_id == other.message_id

    def __hash__(self) -> int:
        """使用不可变的实体身份计算哈希值。"""
        return hash(self.message_id)


def create_chat_message(
    *,
    client_message_id: ClientMessageId,
    sender_id: UserId,
    recipient_id: UserId,
    content: MessageContent,
) -> ChatMessage:
    """创建具有服务端身份和 UTC 创建时间的聊天消息。"""
    return ChatMessage(
        message_id=MessageId.generate(),
        client_message_id=client_message_id,
        sender_id=sender_id,
        recipient_id=recipient_id,
        content=content,
        created_at=datetime.now(timezone.utc),
    )

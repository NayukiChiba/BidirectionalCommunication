"""发送消息应用用例的输入与结果。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from src.application.exceptions import InvalidMessageHistoryQuery
from src.domain import ChatMessage

DEFAULT_HISTORY_PAGE_SIZE = 50
MAX_HISTORY_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class SendMessageCommand:
    """与具体传输协议无关的发送消息命令。"""

    sender_id: str
    conversation_id: UUID
    content: str
    client_message_id: UUID


class DeliveryOutcome(StrEnum):
    """实时推送尝试的观测结果，不表示客户端已经确认。"""

    PUSHED = "pushed"
    RECIPIENT_OFFLINE = "recipient_offline"
    FAILED = "failed"


class SendMessageStatus(StrEnum):
    """发送消息用例的最终结果。"""

    ACCEPTED = "accepted"
    STORAGE_FAILED = "storage_failed"
    INVALID_MESSAGE = "invalid_message"
    CONVERSATION_UNAVAILABLE = "conversation_unavailable"


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    """供入口层转换为具体协议响应的应用结果。"""

    status: SendMessageStatus
    message: ChatMessage | None = None
    push_outcome: DeliveryOutcome | None = None


@dataclass(frozen=True, slots=True)
class MessageCursor:
    """历史消息正向分页的排他游标。"""

    created_at: datetime
    message_id: UUID

    def __post_init__(self) -> None:
        """验证游标字段并规范化时间为 UTC。"""
        if not isinstance(self.created_at, datetime):
            raise InvalidMessageHistoryQuery("历史消息游标时间类型无效")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidMessageHistoryQuery("历史消息游标时间必须包含时区")
        if not isinstance(self.message_id, UUID):
            raise InvalidMessageHistoryQuery("历史消息游标必须包含有效消息标识")
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )

    @classmethod
    def fromMessage(cls, message: ChatMessage) -> "MessageCursor":
        """根据一条消息创建其后的排他游标。"""
        return cls(
            created_at=message.created_at,
            message_id=message.message_id.value,
        )


@dataclass(frozen=True, slots=True)
class MessageHistoryQuery:
    """按会话和可选游标查询当前用户可见的单聊历史。"""

    user_id: str
    conversation_id: UUID
    cursor: MessageCursor | None = None
    limit: int = DEFAULT_HISTORY_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class MessageHistoryPage:
    """按时间正向排列的一页聊天消息。"""

    messages: tuple[ChatMessage, ...]
    next_cursor: MessageCursor | None
    has_more: bool

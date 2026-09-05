"""累计确认和重连同步用例的输入与结果。"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from src.domain import ChatMessage, MessagePosition


class PositionKind(StrEnum):
    """客户端可以显式推进的两种累计位置。"""

    DELIVERED = "delivered"
    READ = "read"


@dataclass(frozen=True, slots=True)
class AdvancePositionCommand:
    """当前用户确认某个会话消息位置的命令。"""

    user_id: str
    conversation_id: UUID
    message_id: UUID
    kind: PositionKind


@dataclass(frozen=True, slots=True)
class AdvancePositionResult:
    """累计位置推进结果。"""

    kind: PositionKind
    requested_position: MessagePosition
    effective_position: MessagePosition | None
    advanced: bool


@dataclass(frozen=True, slots=True)
class SyncMessagesCommand:
    """重连后从客户端最后已知位置继续同步的命令。"""

    user_id: str
    conversation_id: UUID
    after_message_id: UUID | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class SyncMessagesResult:
    """一次可重复请求的缺失消息同步结果。"""

    messages: tuple[ChatMessage, ...]
    has_more: bool

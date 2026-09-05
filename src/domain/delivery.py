"""会话成员的累计送达与已读位置。"""

from dataclasses import dataclass
from datetime import datetime, timezone

from src.domain.conversation import ConversationId
from src.domain.exceptions import InvalidMessagePosition, ReadPositionBeyondDelivery
from src.domain.identifiers import UserId
from src.domain.message import MessageId


@dataclass(frozen=True, slots=True)
class MessagePosition:
    """以创建时间和唯一消息 ID 表示的稳定会话位置。"""

    created_at: datetime
    message_id: MessageId

    def __post_init__(self) -> None:
        """验证位置组成并统一时间为 UTC。"""
        if not isinstance(self.created_at, datetime):
            raise InvalidMessagePosition("消息位置时间必须是 datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidMessagePosition("消息位置时间必须包含时区")
        if not isinstance(self.message_id, MessageId):
            raise InvalidMessagePosition("消息位置必须包含 MessageId")
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )

    @property
    def sortKey(self) -> tuple[datetime, str]:
        """返回与历史查询排序完全一致的比较键。"""
        return self.created_at, str(self.message_id)

    def isAfter(self, other: "MessagePosition") -> bool:
        """判断当前位置是否严格位于另一位置之后。"""
        return self.sortKey > other.sortKey


@dataclass(frozen=True, slots=True)
class ConversationProgress:
    """一名会话成员的累计送达和已读位置快照。"""

    conversation_id: ConversationId
    member_id: UserId
    delivered_position: MessagePosition | None = None
    read_position: MessagePosition | None = None

    def __post_init__(self) -> None:
        """保证已读位置不会超过已送达位置。"""
        if not isinstance(self.conversation_id, ConversationId):
            raise InvalidMessagePosition("进度必须包含 ConversationId")
        if not isinstance(self.member_id, UserId):
            raise InvalidMessagePosition("进度必须包含成员 UserId")
        if self.read_position is not None and (
            self.delivered_position is None
            or self.read_position.isAfter(self.delivered_position)
        ):
            raise ReadPositionBeyondDelivery("已读位置不能超过已送达位置")

    def requireReadable(self, position: MessagePosition) -> None:
        """确认目标位置已经被该成员累计接收。"""
        if self.delivered_position is None or position.isAfter(self.delivered_position):
            raise ReadPositionBeyondDelivery("不能确认尚未送达的消息为已读")

"""一对一会话聚合。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.domain.exceptions import (
    ConversationMemberRequired,
    InvalidConversation,
    InvalidConversationId,
)
from src.domain.identifiers import UserId


@dataclass(frozen=True, slots=True)
class ConversationId:
    """一对一会话的稳定服务端标识。"""

    value: UUID

    def __post_init__(self) -> None:
        """拒绝 UUID 以外的会话标识。"""
        if not isinstance(self.value, UUID):
            raise InvalidConversationId("会话标识必须是 UUID")

    @classmethod
    def generate(cls) -> "ConversationId":
        """生成新的会话标识。"""
        return cls(uuid4())

    def __str__(self) -> str:
        """返回持久化和传输边界使用的文本。"""
        return str(self.value)


@dataclass(frozen=True, eq=False, slots=True)
class Conversation:
    """固定包含两名不同用户的一对一会话聚合根。"""

    conversation_id: ConversationId
    members: frozenset[UserId]
    created_at: datetime

    def __post_init__(self) -> None:
        """保护会话身份、成员数量和创建时间不变量。"""
        if not isinstance(self.conversation_id, ConversationId):
            raise InvalidConversation("conversation_id 必须是 ConversationId")
        if not isinstance(self.members, frozenset):
            raise InvalidConversation("members 必须是不可变集合")
        if len(self.members) != 2 or not all(
            isinstance(member, UserId) for member in self.members
        ):
            raise InvalidConversation("一对一会话必须恰好包含两名不同用户")
        if not isinstance(self.created_at, datetime):
            raise InvalidConversation("会话创建时间必须是 datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidConversation("会话创建时间必须包含时区")
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )

    @property
    def memberPairKey(self) -> str:
        """返回与成员输入顺序无关的数据库幂等键。"""
        return ":".join(sorted(str(member) for member in self.members))

    def hasMember(self, userId: UserId) -> bool:
        """判断用户是否属于当前会话。"""
        return userId in self.members

    def requireMember(self, userId: UserId) -> None:
        """拒绝非成员访问会话内资源。"""
        if not self.hasMember(userId):
            raise ConversationMemberRequired("用户不是当前会话成员")

    def getOtherMember(self, userId: UserId) -> UserId:
        """返回一对一会话中除当前用户外的另一名成员。"""
        self.requireMember(userId)
        return next(member for member in self.members if member != userId)

    def __eq__(self, other: object) -> bool:
        """通过会话 ID 判断实体身份。"""
        return (
            isinstance(other, Conversation)
            and self.conversation_id == other.conversation_id
        )

    def __hash__(self) -> int:
        """使用稳定会话身份计算哈希。"""
        return hash(self.conversation_id)


def createConversation(firstMemberId: UserId, secondMemberId: UserId) -> Conversation:
    """创建恰好包含两名不同用户的新会话。"""
    return Conversation(
        conversation_id=ConversationId.generate(),
        members=frozenset((firstMemberId, secondMemberId)),
        created_at=datetime.now(timezone.utc),
    )

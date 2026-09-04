"""Conversation 聚合与 SQLAlchemy 记录之间的显式转换。"""

from uuid import UUID

from src.adapters.database.messageMapper import normalizeDatabaseDatetime
from src.adapters.database.models import (
    ConversationMemberRecord,
    ConversationRecord,
)
from src.domain import Conversation, ConversationId, UserId


def toConversationRecord(conversation: Conversation) -> ConversationRecord:
    """把完整会话聚合转换成根记录和两个成员记录。"""
    sortedMembers = sorted(conversation.members, key=str)
    record = ConversationRecord(
        conversationId=str(conversation.conversation_id),
        memberPairKey=conversation.memberPairKey,
        createdAt=conversation.created_at,
    )
    record.members = [
        ConversationMemberRecord(
            conversationId=str(conversation.conversation_id),
            userId=str(member),
            memberPosition=position,
        )
        for position, member in enumerate(sortedMembers, start=1)
    ]
    return record


def toDomainConversation(record: ConversationRecord) -> Conversation:
    """从根记录和成员记录重新构造并验证会话聚合。"""
    return Conversation(
        conversation_id=ConversationId(UUID(record.conversationId)),
        members=frozenset(UserId(member.userId) for member in record.members),
        created_at=normalizeDatabaseDatetime(record.createdAt),
    )

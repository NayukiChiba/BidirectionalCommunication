"""一对一 Conversation 聚合测试。"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain import (
    Conversation,
    ConversationId,
    ConversationMemberRequired,
    InvalidConversation,
    UserId,
    createConversation,
)


def test_conversation_requires_exactly_two_distinct_members() -> None:
    """领域聚合不能表示自聊、单成员或重复成员会话。"""
    userId = UserId("user-a")

    with pytest.raises(InvalidConversation):
        createConversation(userId, userId)


def test_member_pair_key_ignores_input_order() -> None:
    """成员顺序变化不能改变一对一会话的业务身份组合。"""
    userA = UserId("user-a")
    userB = UserId("user-b")

    first = createConversation(userA, userB)
    second = createConversation(userB, userA)

    assert first.memberPairKey == second.memberPairKey == "user-a:user-b"


def test_conversation_controls_member_access_and_other_member() -> None:
    """聚合根统一判断成员身份并返回另一名成员。"""
    userA = UserId("user-a")
    userB = UserId("user-b")
    conversation = createConversation(userA, userB)

    conversation.requireMember(userA)

    assert conversation.hasMember(userB) is True
    assert conversation.getOtherMember(userA) == userB
    with pytest.raises(ConversationMemberRequired):
        conversation.requireMember(UserId("user-c"))


def test_conversation_is_immutable_entity_identified_by_id() -> None:
    """聚合成员不可外部修改，会话身份只由 ConversationId 决定。"""
    conversationId = ConversationId(uuid4())
    first = Conversation(
        conversation_id=conversationId,
        members=frozenset((UserId("user-a"), UserId("user-b"))),
        created_at=datetime.now(timezone.utc),
    )
    second = Conversation(
        conversation_id=conversationId,
        members=frozenset((UserId("user-c"), UserId("user-d"))),
        created_at=datetime.now(timezone.utc),
    )

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.members = frozenset()  # type: ignore[misc]

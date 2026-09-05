"""累计消息位置领域规则测试。"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.domain import (
    ConversationId,
    ConversationProgress,
    MessageId,
    MessagePosition,
    ReadPositionBeyondDelivery,
    UserId,
)


def createPosition(sequence: int) -> MessagePosition:
    """创建时间相同但消息 ID 有稳定次序的位置。"""
    return MessagePosition(
        created_at=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc),
        message_id=MessageId(UUID(int=sequence)),
    )


def test_message_position_uses_unique_message_id_as_tie_breaker() -> None:
    """相同创建时间下必须由消息 ID 提供唯一稳定顺序。"""
    first = createPosition(1)
    second = createPosition(2)

    assert second.isAfter(first) is True
    assert first.isAfter(second) is False


def test_read_position_cannot_exceed_delivered_position() -> None:
    """成员不能把尚未确认收到的位置标记为已读。"""
    delivered = createPosition(1)
    progress = ConversationProgress(
        conversation_id=ConversationId(uuid4()),
        member_id=UserId("user-a"),
        delivered_position=delivered,
    )

    progress.requireReadable(delivered)
    with pytest.raises(ReadPositionBeyondDelivery):
        progress.requireReadable(createPosition(2))


def test_progress_snapshot_rejects_inconsistent_read_position() -> None:
    """从持久化边界恢复进度时也必须重新验证已读不变量。"""
    with pytest.raises(ReadPositionBeyondDelivery):
        ConversationProgress(
            conversation_id=ConversationId(uuid4()),
            member_id=UserId("user-a"),
            delivered_position=createPosition(1),
            read_position=createPosition(2),
        )

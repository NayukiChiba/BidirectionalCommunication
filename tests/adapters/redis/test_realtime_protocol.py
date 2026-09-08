"""Redis 内部实时协议和实例内事件去重测试。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError

from src.adapters.redis import RealtimeDeliveryEvent, RealtimeMessagePayload
from src.adapters.redis.redisRealtimeGateway import (
    RecentEventCache,
    RedisRealtimeGateway,
)
from src.adapters.webSocketConnectionManager import (
    ConnectionManager,
    ConnectionSendOutcome,
)


class FakeClock:
    """手动推进的单调时钟。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def createPayload(recipientId: str = "user-b") -> RealtimeMessagePayload:
    """创建合法的最小跨实例消息载荷。"""
    return RealtimeMessagePayload(
        type="message",
        server_message_id=uuid4(),
        client_message_id=uuid4(),
        conversation_id=uuid4(),
        sender_id="user-a",
        recipient_id=recipientId,
        content="internal-message",
        sent_at=datetime.now(timezone.utc),
    )


def test_internal_protocol_is_versioned_and_rejects_extra_fields() -> None:
    """内部事件必须显式版本化，未知字段不能静默传播。"""
    event = RealtimeDeliveryEvent(
        source_instance_id="instance-a",
        target_user_id="user-b",
        payload=createPayload(),
    )

    restored = RealtimeDeliveryEvent.fromJson(event.toJson())

    assert restored == event
    with pytest.raises(ValidationError):
        RealtimeDeliveryEvent.model_validate(
            {**event.model_dump(), "unexpected": "value"}
        )


def test_recent_event_cache_is_bounded_and_expires_without_sleep() -> None:
    """重复事件在 TTL 内被拒绝，过期后不永久占用内存。"""
    clock = FakeClock()
    cache = RecentEventCache(ttlSeconds=10, maxEvents=2, clock=clock)
    eventId = uuid4()

    assert cache.alreadySeen(eventId) is False
    assert cache.alreadySeen(eventId) is True
    cache.alreadySeen(uuid4())
    cache.alreadySeen(uuid4())
    assert len(cache._events) == 2

    clock.now = 11

    assert cache.alreadySeen(eventId) is False


@pytest.mark.asyncio
async def test_duplicate_internal_event_is_sent_to_local_websocket_once() -> None:
    """即使内部事件重复到达，也不能让客户端重复展示。"""
    localConnections = ConnectionManager()
    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.send_json = AsyncMock()
    await localConnections.connect("user-b", websocket)
    gateway = RedisRealtimeGateway(
        localConnections,
        MagicMock(),
        instanceId="instance-b",
        channelPrefix="test-chat",
        presenceLeaseSeconds=30,
        presenceRefreshSeconds=10,
        subscriberRetrySeconds=1,
        operationTimeoutSeconds=1,
        recentEventTtlSeconds=60,
        recentEventLimit=100,
    )
    event = RealtimeDeliveryEvent(
        source_instance_id="instance-a",
        target_user_id="user-b",
        payload=createPayload(),
    )
    repeatedMessageEvent = RealtimeDeliveryEvent(
        source_instance_id="instance-a",
        target_user_id="user-b",
        payload=event.payload,
    )

    await gateway._handleEvent(event.toJson())
    await gateway._handleEvent(repeatedMessageEvent.toJson())

    websocket.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_failure_degrades_realtime_without_fake_offline_success() -> None:
    """Redis 不可用时明确返回失败，由数据库重连补偿承担可靠性。"""

    class FailingRedis:
        async def get(self, key: str) -> None:
            raise ConnectionError("redis unavailable")

    gateway = RedisRealtimeGateway(
        ConnectionManager(),
        FailingRedis(),  # type: ignore[arg-type]
        instanceId="instance-a",
        channelPrefix="test-chat",
        presenceLeaseSeconds=30,
        presenceRefreshSeconds=10,
        subscriberRetrySeconds=1,
        operationTimeoutSeconds=1,
        recentEventTtlSeconds=60,
        recentEventLimit=100,
    )

    outcome = await gateway.deliver_to_user(
        "user-b",
        createPayload().model_dump(mode="json"),
    )

    assert outcome is ConnectionSendOutcome.FAILED

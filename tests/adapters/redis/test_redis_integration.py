"""真实 Redis 在线租约和跨实例 Pub/Sub 集成测试。"""

import asyncio
import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.adapters.redis import (
    PresenceLeaseRepository,
    RealtimeDeliveryEvent,
    RedisRealtimeGateway,
)
from src.adapters.redis.connection import createRedisClient
from src.adapters.webSocketConnectionManager import (
    ConnectionManager,
    ConnectionSendOutcome,
)
from tests.adapters.redis.test_realtime_protocol import createPayload


@pytest_asyncio.fixture
async def redisClient() -> AsyncIterator[Redis]:
    """连接隔离测试 Redis；未配置时跳过真实集成测试。"""
    redisUrl = os.getenv("TEST_REDIS_URL")
    if not redisUrl:
        pytest.skip("未设置 TEST_REDIS_URL，跳过 Redis 集成测试")
    client = createRedisClient(redisUrl, maxConnections=10)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


async def waitForMissingKey(client: Redis, key: str) -> None:
    """轮询真实 TTL，到期即返回。"""
    while await client.exists(key):
        await asyncio.sleep(0.05)


async def waitForSubscriber(client: Redis, channel: str) -> None:
    """等待订阅恢复并重新出现在 Redis 频道统计中。"""
    while True:
        subscriptions = await client.pubsub_numsub(channel)
        if subscriptions and subscriptions[0][1] == 1:
            return
        await asyncio.sleep(0.05)


def createWebSocket(delivered: asyncio.Event | None = None) -> MagicMock:
    """创建可以用事件报告实时投递完成的本地 WebSocket。"""
    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()

    async def sendJson(data: dict[str, object]) -> None:
        if delivered is not None:
            delivered.set()

    websocket.send_json = AsyncMock(side_effect=sendJson)
    return websocket


@pytest.mark.asyncio
async def test_presence_lease_expires_after_crashed_instance(
    redisClient: Redis,
) -> None:
    """没有执行下线清理的崩溃实例不会留下永久在线状态。"""
    repository = PresenceLeaseRepository(
        redisClient,
        instanceId="crashed-instance",
        leaseSeconds=1,
        keyPrefix="integration-chat",
    )
    await repository.markOnline("user-a")
    key = repository.keyFor("user-a")

    await asyncio.wait_for(waitForMissingKey(redisClient, key), timeout=2)

    assert await repository.getInstance("user-a") is None


@pytest.mark.asyncio
async def test_new_instance_lease_cannot_be_stolen_or_deleted_by_old_instance(
    redisClient: Redis,
) -> None:
    """用户迁移实例后，旧实例的心跳和下线清理不能覆盖新租约。"""
    oldRepository = PresenceLeaseRepository(
        redisClient,
        instanceId="old-instance",
        leaseSeconds=10,
        keyPrefix="takeover-chat",
    )
    newRepository = PresenceLeaseRepository(
        redisClient,
        instanceId="new-instance",
        leaseSeconds=10,
        keyPrefix="takeover-chat",
    )
    await oldRepository.markOnline("user-a")
    await newRepository.markOnline("user-a")

    assert await oldRepository.refresh("user-a") is False
    assert await oldRepository.remove("user-a") is False
    assert await newRepository.getInstance("user-a") == "new-instance"


@pytest.mark.asyncio
async def test_two_instances_route_to_only_target_local_websocket(
    redisClient: Redis,
) -> None:
    """源实例通过目标租约和专属频道投递到另一实例的本地连接。"""
    redisUrl = os.environ["TEST_REDIS_URL"]
    sourceClient = createRedisClient(redisUrl, maxConnections=10)
    targetClient = createRedisClient(redisUrl, maxConnections=10)
    sourceLocal = ConnectionManager()
    targetLocal = ConnectionManager()
    sourceGateway = RedisRealtimeGateway(
        sourceLocal,
        sourceClient,
        instanceId="instance-a",
        channelPrefix="route-chat",
        presenceLeaseSeconds=10,
        presenceRefreshSeconds=2,
        subscriberRetrySeconds=0.1,
        operationTimeoutSeconds=2,
        recentEventTtlSeconds=30,
        recentEventLimit=100,
    )
    targetGateway = RedisRealtimeGateway(
        targetLocal,
        targetClient,
        instanceId="instance-b",
        channelPrefix="route-chat",
        presenceLeaseSeconds=10,
        presenceRefreshSeconds=2,
        subscriberRetrySeconds=0.1,
        operationTimeoutSeconds=2,
        recentEventTtlSeconds=30,
        recentEventLimit=100,
    )
    delivered = asyncio.Event()
    targetWebSocket = createWebSocket(delivered)
    try:
        await asyncio.gather(sourceGateway.start(), targetGateway.start())
        await targetGateway.connect("user-b", targetWebSocket)

        outcome = await sourceGateway.deliver_to_user(
            "user-b",
            createPayload().model_dump(mode="json"),
        )
        await asyncio.wait_for(delivered.wait(), timeout=2)

        assert outcome is ConnectionSendOutcome.ROUTED
        targetWebSocket.send_json.assert_awaited_once()
        assert sourceLocal.is_online("user-b") is False
        assert targetLocal.is_online("user-b") is True
    finally:
        await asyncio.gather(sourceGateway.close(), targetGateway.close())


@pytest.mark.asyncio
async def test_subscriber_reconnects_after_redis_kills_pubsub_connection(
    redisClient: Redis,
) -> None:
    """订阅连接断开后实例应重新订阅并恢复后续实时事件处理。"""
    redisUrl = os.environ["TEST_REDIS_URL"]
    targetClient = createRedisClient(redisUrl, maxConnections=10)
    localConnections = ConnectionManager()
    gateway = RedisRealtimeGateway(
        localConnections,
        targetClient,
        instanceId="recovering-instance",
        channelPrefix="recovery-chat",
        presenceLeaseSeconds=10,
        presenceRefreshSeconds=2,
        subscriberRetrySeconds=0.1,
        operationTimeoutSeconds=2,
        recentEventTtlSeconds=30,
        recentEventLimit=100,
    )
    delivered = asyncio.Event()
    websocket = createWebSocket(delivered)
    try:
        await gateway.start()
        await gateway.connect("user-b", websocket)
        killedConnections = await redisClient.execute_command(
            "CLIENT",
            "KILL",
            "TYPE",
            "PUBSUB",
        )
        assert int(killedConnections) >= 1

        await asyncio.wait_for(
            waitForSubscriber(redisClient, gateway._channel),
            timeout=2,
        )
        event = RealtimeDeliveryEvent(
            source_instance_id="source-instance",
            target_user_id="user-b",
            payload=createPayload(),
        )
        await redisClient.publish(gateway._channel, event.toJson())
        await asyncio.wait_for(delivered.wait(), timeout=2)

        websocket.send_json.assert_awaited_once()
    finally:
        await gateway.close()

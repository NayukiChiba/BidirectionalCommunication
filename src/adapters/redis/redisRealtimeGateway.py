"""组合本地 WebSocket、Redis 在线租约和跨实例 Pub/Sub 的网关。"""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from uuid import UUID

from fastapi import WebSocket
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.adapters.redis.presenceLeaseRepository import PresenceLeaseRepository
from src.adapters.redis.realtimeProtocol import (
    RealtimeDeliveryEvent,
    RealtimeMessagePayload,
)
from src.adapters.webSocketConnectionManager import (
    ConnectionManager,
    ConnectionSendOutcome,
)

logger = logging.getLogger(__name__)


class RecentEventCache:
    """在一个实例内按 TTL 和容量限制去重内部事件。"""

    def __init__(
        self,
        ttlSeconds: float,
        maxEvents: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """保存有界去重参数并允许测试注入时钟。"""
        self._ttlSeconds = ttlSeconds
        self._maxEvents = maxEvents
        self._clock = clock
        self._events: OrderedDict[UUID, float] = OrderedDict()

    def alreadySeen(self, eventId: UUID) -> bool:
        """记录新事件，已存在且未过期时返回 True。"""
        now = self._clock()
        expiredBefore = now - self._ttlSeconds
        while self._events:
            _, recordedAt = next(iter(self._events.items()))
            if recordedAt > expiredBefore:
                break
            self._events.popitem(last=False)
        if eventId in self._events:
            return True
        self._events[eventId] = now
        while len(self._events) > self._maxEvents:
            self._events.popitem(last=False)
        return False


class RedisRealtimeGateway:
    """仅跨实例路由瞬时事件，可靠消息始终来自数据库。"""

    def __init__(
        self,
        localConnections: ConnectionManager,
        redisClient: Redis,
        *,
        instanceId: str,
        channelPrefix: str,
        presenceLeaseSeconds: int,
        presenceRefreshSeconds: float,
        subscriberRetrySeconds: float,
        operationTimeoutSeconds: float,
        recentEventTtlSeconds: float,
        recentEventLimit: int,
    ) -> None:
        """保存实例级 Redis 客户端、租约和后台任务配置。"""
        self._localConnections = localConnections
        self._redis = redisClient
        self._instanceId = instanceId
        self._channel = f"{channelPrefix}:instance:{instanceId}"
        self._presence = PresenceLeaseRepository(
            redisClient,
            instanceId=instanceId,
            leaseSeconds=presenceLeaseSeconds,
            keyPrefix=channelPrefix,
        )
        self._presenceRefreshSeconds = presenceRefreshSeconds
        self._subscriberRetrySeconds = subscriberRetrySeconds
        self._operationTimeoutSeconds = operationTimeoutSeconds
        self._recentMessages = RecentEventCache(
            recentEventTtlSeconds,
            recentEventLimit,
        )
        self._stopEvent = asyncio.Event()
        self._subscriberReady = asyncio.Event()
        self._subscriberTask: asyncio.Task[None] | None = None
        self._heartbeatTask: asyncio.Task[None] | None = None
        self._cleanupTasks: set[asyncio.Task[None]] = set()

    @property
    def instanceId(self) -> str:
        """返回当前进程的跨实例路由身份。"""
        return self._instanceId

    async def start(self) -> None:
        """启动订阅恢复循环和在线租约刷新循环。"""
        if self._subscriberTask is not None:
            return
        self._stopEvent.clear()
        self._subscriberTask = asyncio.create_task(
            self._runSubscriber(),
            name=f"redis-subscriber-{self._instanceId}",
        )
        self._heartbeatTask = asyncio.create_task(
            self._runHeartbeat(),
            name=f"redis-presence-{self._instanceId}",
        )
        try:
            await asyncio.wait_for(
                self._subscriberReady.wait(),
                timeout=self._operationTimeoutSeconds,
            )
        except TimeoutError:
            logger.warning(
                "redis_subscriber_start_degraded",
                extra={"event": "redis_degraded", "instance_id": self._instanceId},
            )

    async def close(self) -> None:
        """删除当前实例租约，停止任务并关闭 Redis 连接池。"""
        users = self._localConnections.connectedUserIds
        if users:
            await asyncio.gather(
                *(self._removeLeaseBestEffort(userId) for userId in users)
            )
        self._stopEvent.set()
        tasks = [
            task
            for task in (self._subscriberTask, self._heartbeatTask)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._cleanupTasks:
            await asyncio.gather(*self._cleanupTasks, return_exceptions=True)
        await self._redis.aclose()
        self._subscriberTask = None
        self._heartbeatTask = None

    async def connect(self, user_id: str, websocket: WebSocket) -> bool:
        """登记本地连接，并尽力写入带 TTL 的实例租约。"""
        connected = await self._localConnections.connect(user_id, websocket)
        if connected:
            try:
                async with asyncio.timeout(self._operationTimeoutSeconds):
                    await self._presence.markOnline(user_id)
            except (RedisError, TimeoutError):
                self._logRedisFailure("presence_mark_failed", userId=user_id)
        return connected

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """删除本地连接，并异步清理仍属于本实例的租约。"""
        disconnected = self._localConnections.disconnect(user_id, websocket)
        if disconnected:
            task = asyncio.create_task(self._removeLeaseBestEffort(user_id))
            self._cleanupTasks.add(task)
            task.add_done_callback(self._cleanupTasks.discard)
        return disconnected

    async def send_message_to_user(
        self,
        sender_id: str,
        data: dict[str, object],
    ) -> bool:
        """入口响应只发送到当前实例已经建立的本地连接。"""
        return await self._localConnections.send_message_to_user(sender_id, data)

    async def deliver_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> ConnectionSendOutcome:
        """优先本地发送，否则按在线租约发布到目标实例频道。"""
        localOutcome = await self._localConnections.deliver_to_user(user_id, data)
        if localOutcome is ConnectionSendOutcome.DELIVERED:
            return localOutcome
        localDeliveryFailed = localOutcome is ConnectionSendOutcome.FAILED

        try:
            async with asyncio.timeout(self._operationTimeoutSeconds):
                targetInstanceId = await self._presence.getInstance(user_id)
                if targetInstanceId is None:
                    return (
                        ConnectionSendOutcome.FAILED
                        if localDeliveryFailed
                        else ConnectionSendOutcome.RECIPIENT_OFFLINE
                    )
                if targetInstanceId == self._instanceId:
                    await self._presence.remove(user_id)
                    return ConnectionSendOutcome.RECIPIENT_OFFLINE
                event = RealtimeDeliveryEvent(
                    source_instance_id=self._instanceId,
                    target_user_id=user_id,
                    payload=RealtimeMessagePayload.model_validate(data),
                )
                subscribers = await self._redis.publish(
                    self._channelFor(targetInstanceId),
                    event.toJson(),
                )
        except (RedisError, TimeoutError, ValidationError):
            self._logRedisFailure("realtime_publish_failed", userId=user_id)
            return ConnectionSendOutcome.FAILED

        if subscribers < 1:
            return ConnectionSendOutcome.FAILED
        logger.info(
            "realtime_event_routed",
            extra={
                "event": "realtime_routed",
                "instance_id": self._instanceId,
                "target_instance_id": targetInstanceId,
                "internal_event_id": str(event.event_id),
                "user_id": user_id,
            },
        )
        return ConnectionSendOutcome.ROUTED

    async def _runSubscriber(self) -> None:
        """订阅实例频道，断线后持续重建订阅。"""
        while not self._stopEvent.is_set():
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.subscribe(self._channel)
                    self._subscriberReady.set()
                    async for message in pubsub.listen():
                        if self._stopEvent.is_set():
                            return
                        if message.get("type") != "message":
                            continue
                        await self._handleEvent(message.get("data"))
            except asyncio.CancelledError:
                raise
            except RedisError:
                self._subscriberReady.clear()
                self._logRedisFailure("redis_subscriber_disconnected")
                await self._waitForStop(self._subscriberRetrySeconds)

    async def _handleEvent(self, rawEvent: str | bytes | None) -> None:
        """验证、去重并仅向当前实例本地连接投递事件。"""
        if rawEvent is None:
            return
        try:
            event = RealtimeDeliveryEvent.fromJson(rawEvent)
        except ValidationError:
            logger.warning(
                "invalid_realtime_event",
                extra={
                    "event": "realtime_event_rejected",
                    "instance_id": self._instanceId,
                },
            )
            return
        if self._recentMessages.alreadySeen(event.payload.server_message_id):
            logger.info(
                "duplicate_realtime_event_ignored",
                extra={
                    "event": "realtime_duplicate",
                    "instance_id": self._instanceId,
                    "internal_event_id": str(event.event_id),
                },
            )
            return
        outcome = await self._localConnections.deliver_to_user(
            event.target_user_id,
            event.payload.model_dump(mode="json"),
        )
        if outcome is ConnectionSendOutcome.RECIPIENT_OFFLINE:
            await self._removeLeaseBestEffort(event.target_user_id)

    async def _runHeartbeat(self) -> None:
        """周期刷新仍由当前实例拥有的本地用户租约。"""
        while not self._stopEvent.is_set():
            await self._waitForStop(self._presenceRefreshSeconds)
            if self._stopEvent.is_set():
                return
            users = self._localConnections.connectedUserIds
            if not users:
                continue
            try:
                async with asyncio.timeout(self._operationTimeoutSeconds):
                    await asyncio.gather(
                        *(self._presence.refresh(userId) for userId in users)
                    )
            except (RedisError, TimeoutError):
                self._logRedisFailure("presence_refresh_failed")

    async def _removeLeaseBestEffort(self, userId: str) -> None:
        """Redis 不可用时依赖 TTL 最终清理租约。"""
        try:
            async with asyncio.timeout(self._operationTimeoutSeconds):
                await self._presence.remove(userId)
        except (RedisError, TimeoutError):
            self._logRedisFailure("presence_remove_failed", userId=userId)

    async def _waitForStop(self, timeoutSeconds: float) -> None:
        """等待停止信号或重试周期，不使用不可取消的固定 sleep。"""
        try:
            await asyncio.wait_for(self._stopEvent.wait(), timeout=timeoutSeconds)
        except TimeoutError:
            pass

    def _channelFor(self, instanceId: str) -> str:
        """返回目标实例的专属 Pub/Sub 频道。"""
        prefix = self._channel.rsplit(":instance:", maxsplit=1)[0]
        return f"{prefix}:instance:{instanceId}"

    def _logRedisFailure(self, status: str, userId: str | None = None) -> None:
        """记录不包含消息正文和 Redis URL 的降级状态。"""
        logger.warning(
            status,
            extra={
                "event": "redis_degraded",
                "instance_id": self._instanceId,
                "user_id": userId,
                "status": status,
            },
        )

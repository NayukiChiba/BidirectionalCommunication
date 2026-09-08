"""基于 Redis TTL 的用户在线实例租约。"""

from redis.asyncio import Redis

REFRESH_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

REMOVE_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class PresenceLeaseRepository:
    """让新实例接管租约，并阻止旧实例刷新或删除新租约。"""

    def __init__(
        self,
        redisClient: Redis,
        *,
        instanceId: str,
        leaseSeconds: int,
        keyPrefix: str,
    ) -> None:
        """保存共享 Redis 客户端和当前实例身份。"""
        self._redis = redisClient
        self._instanceId = instanceId
        self._leaseSeconds = leaseSeconds
        self._keyPrefix = keyPrefix

    def keyFor(self, userId: str) -> str:
        """返回用户在线租约键。"""
        return f"{self._keyPrefix}:presence:{userId}"

    async def markOnline(self, userId: str) -> None:
        """创建租约；同一用户的新实例会覆盖旧实例。"""
        await self._redis.set(
            self.keyFor(userId),
            self._instanceId,
            ex=self._leaseSeconds,
        )

    async def getInstance(self, userId: str) -> str | None:
        """返回当前租约指向的实例，过期或不存在时返回 None。"""
        value = await self._redis.get(self.keyFor(userId))
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def refresh(self, userId: str) -> bool:
        """仅当租约仍属于当前实例时延长 TTL。"""
        result = await self._redis.eval(
            REFRESH_LEASE_SCRIPT,
            1,
            self.keyFor(userId),
            self._instanceId,
            self._leaseSeconds,
        )
        return bool(result)

    async def remove(self, userId: str) -> bool:
        """仅删除仍属于当前实例的租约。"""
        result = await self._redis.eval(
            REMOVE_LEASE_SCRIPT,
            1,
            self.keyFor(userId),
            self._instanceId,
        )
        return bool(result)

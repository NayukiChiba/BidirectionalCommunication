"""Redis 跨实例实时路由适配器公开接口。"""

from src.adapters.redis.connection import createRedisClient
from src.adapters.redis.presenceLeaseRepository import PresenceLeaseRepository
from src.adapters.redis.realtimeProtocol import (
    INTERNAL_PROTOCOL_VERSION,
    RealtimeDeliveryEvent,
    RealtimeMessagePayload,
)
from src.adapters.redis.redisRealtimeGateway import RedisRealtimeGateway

__all__ = [
    "INTERNAL_PROTOCOL_VERSION",
    "PresenceLeaseRepository",
    "RealtimeDeliveryEvent",
    "RealtimeMessagePayload",
    "RedisRealtimeGateway",
    "createRedisClient",
]

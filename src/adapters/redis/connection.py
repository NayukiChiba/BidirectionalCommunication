"""应用生命周期共享的异步 Redis 客户端配置。"""

from redis.asyncio import Redis


def createRedisClient(redisUrl: str, maxConnections: int) -> Redis:
    """创建带有界连接池和响应解码的惰性异步客户端。"""
    return Redis.from_url(
        redisUrl,
        decode_responses=True,
        max_connections=maxConnections,
        health_check_interval=15,
    )

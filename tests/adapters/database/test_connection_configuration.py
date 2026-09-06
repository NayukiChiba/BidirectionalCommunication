"""SQLite 与 PostgreSQL 异步连接配置测试。"""

import pytest

from src.adapters.database import (
    createAsyncDatabaseEngine,
    normalizeAsyncDatabaseUrl,
)


def test_postgresql_url_uses_asyncpg_dialect() -> None:
    """通用 PostgreSQL URL 应规范化为 asyncpg 异步方言。"""
    url = normalizeAsyncDatabaseUrl("postgresql://chat:secret@localhost:5432/chat")

    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "chat"
    assert url.password == "secret"


def test_unsupported_database_backend_is_rejected() -> None:
    """未验证的数据库方言不能静默进入运行时。"""
    with pytest.raises(ValueError, match="不支持的数据库后端"):
        normalizeAsyncDatabaseUrl("mysql://localhost/chat")


@pytest.mark.asyncio
async def test_postgresql_engine_has_bounded_healthy_pool() -> None:
    """PostgreSQL Engine 应应用连接池容量和断线前探测配置。"""
    engine = createAsyncDatabaseEngine(
        "postgresql+psycopg://chat:secret@localhost:5432/chat",
        poolSize=4,
        maxOverflow=6,
        poolTimeoutSeconds=7,
        poolRecycleSeconds=600,
    )
    try:
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 6
        assert engine.pool._timeout == 7
        assert engine.pool._recycle == 600
        assert engine.pool._pre_ping is True
    finally:
        await engine.dispose()

"""SQLite 与 PostgreSQL 共用的异步 SQLAlchemy 连接配置。"""

import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import DATABASE_PATH

SUPPORTED_DATABASE_BACKENDS = {"sqlite", "postgresql"}


def createAsyncSqliteUrl(databasePath: Path = DATABASE_PATH) -> URL:
    """根据 pathlib 路径创建 aiosqlite 数据库 URL。"""
    resolvedPath = databasePath.expanduser().resolve()
    return URL.create("sqlite+aiosqlite", database=str(resolvedPath))


def normalizeAsyncDatabaseUrl(databaseUrl: str | URL) -> URL:
    """校验后端并为已支持数据库选择明确异步驱动。"""
    url = make_url(databaseUrl) if isinstance(databaseUrl, str) else databaseUrl
    backend = url.get_backend_name()
    if backend not in SUPPORTED_DATABASE_BACKENDS:
        raise ValueError(f"不支持的数据库后端：{backend}")
    if backend == "sqlite":
        return url.set(drivername="sqlite+aiosqlite")
    return url.set(drivername="postgresql+asyncpg")


def createAsyncDatabaseEngine(
    databaseUrl: str | URL,
    *,
    poolSize: int = 5,
    maxOverflow: int = 10,
    poolTimeoutSeconds: float = 30.0,
    poolRecycleSeconds: int = 1_800,
    echo: bool = False,
) -> AsyncEngine:
    """按数据库 URL 创建带连接健康检查的长期 AsyncEngine。"""
    normalizedUrl = normalizeAsyncDatabaseUrl(databaseUrl)
    backend = normalizedUrl.get_backend_name()
    engineOptions: dict[str, object] = {
        "echo": echo,
        "pool_pre_ping": True,
    }
    if backend == "postgresql":
        engineOptions.update(
            pool_size=poolSize,
            max_overflow=maxOverflow,
            pool_timeout=poolTimeoutSeconds,
            pool_recycle=poolRecycleSeconds,
        )
    else:
        database = normalizedUrl.database
        if database and database != ":memory:":
            Path(database).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )

    engine = create_async_engine(normalizedUrl, **engineOptions)
    if backend == "sqlite":
        _enableSqliteForeignKeys(engine)
    return engine


def _enableSqliteForeignKeys(engine: AsyncEngine) -> None:
    """为每条 SQLite 连接显式启用外键约束。"""

    @event.listens_for(engine.sync_engine, "connect")
    def enableForeignKeys(
        databaseConnection: sqlite3.Connection,
        connectionRecord: object,
    ) -> None:
        del connectionRecord
        cursor = databaseConnection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def createAsyncSqliteEngine(
    databasePath: Path = DATABASE_PATH,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """兼容现有测试的 SQLite AsyncEngine 创建入口。"""
    return createAsyncDatabaseEngine(createAsyncSqliteUrl(databasePath), echo=echo)


def createAsyncSessionFactory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建绑定 Engine 且提交后不隐式过期的 AsyncSession 工厂。"""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

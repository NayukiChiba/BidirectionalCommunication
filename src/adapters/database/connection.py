"""
异步数据库连接配置

功能：
1. 根据 pathlib 路径创建 aiosqlite URL 和 AsyncEngine
2. 创建每次调用都返回独立 AsyncSession 的工厂
"""

import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import DATABASE_PATH


def createAsyncSqliteUrl(databasePath: Path = DATABASE_PATH) -> URL:
    """根据 pathlib 路径创建 aiosqlite 数据库 URL。"""
    resolvedPath = databasePath.expanduser().resolve()
    return URL.create("sqlite+aiosqlite", database=str(resolvedPath))


def createAsyncSqliteEngine(
    databasePath: Path = DATABASE_PATH,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """创建指向 SQLite 文件的异步 Engine。"""
    resolvedPath = databasePath.expanduser().resolve()
    resolvedPath.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        createAsyncSqliteUrl(resolvedPath),
        echo=echo,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enableForeignKeys(
        databaseConnection: sqlite3.Connection,
        connectionRecord: object,
    ) -> None:
        """为每条 SQLite 连接显式启用外键约束。"""
        del connectionRecord
        cursor = databaseConnection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def createAsyncSessionFactory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建绑定 Engine 且提交后不隐式过期的 AsyncSession 工厂。"""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

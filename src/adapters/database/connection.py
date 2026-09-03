"""
同步数据库连接配置

功能：
1. 根据 pathlib 路径创建 SQLite Engine
2. 创建配置统一的同步 Session 工厂
3. 为当前学习阶段创建数据库元数据
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.database.models import DatabaseBase
from src.config import DATABASE_PATH


def createSqliteEngine(
    databasePath: Path = DATABASE_PATH,
    *,
    echo: bool = False,
) -> Engine:
    """
    创建指向 SQLite 文件的同步 Engine

    Args:
        databasePath (Path): SQLite 数据库文件路径。
        echo (bool): 是否输出 SQL 日志。

    Returns:
        Engine: 可复用的同步数据库连接工厂。
    """
    resolvedPath = databasePath.expanduser().resolve()
    resolvedPath.parent.mkdir(parents=True, exist_ok=True)
    databaseUrl = URL.create("sqlite+pysqlite", database=str(resolvedPath))
    return create_engine(databaseUrl, echo=echo)


def createSessionFactory(engine: Engine) -> sessionmaker[Session]:
    """
    创建绑定到指定 Engine 的同步 Session 工厂

    保留 SQLAlchemy 的 autoflush 和 expire_on_commit 默认行为，便于学习
    标准 Session 生命周期。
    """
    return sessionmaker(bind=engine)


def createDatabaseSchema(engine: Engine) -> None:
    """
    按 ORM 元数据创建当前学习数据库结构

    该函数仅用于 Issue 12 的实验和测试；正式结构迁移将在 Alembic
    里管理。
    """
    DatabaseBase.metadata.create_all(engine)

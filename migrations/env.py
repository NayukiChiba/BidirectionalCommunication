"""Alembic 迁移运行环境。"""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL, make_url

from src.adapters.database.connection import createSqliteUrl
from src.adapters.database.models import DatabaseBase
from src.config import DATABASE_PATH

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = DatabaseBase.metadata


def getDatabaseUrl() -> URL:
    """优先使用测试或命令行覆盖，否则读取项目统一 SQLite 配置。"""
    arguments = context.get_x_argument(as_dictionary=True)
    databasePath = arguments.get("database_path")
    if databasePath:
        return createSqliteUrl(Path(databasePath))

    configuredUrl = config.get_main_option("sqlalchemy.url")
    if configuredUrl:
        return make_url(configuredUrl)

    return createSqliteUrl(DATABASE_PATH)


def ensureSqliteDirectory(databaseUrl: URL) -> None:
    """在线迁移前确保文件 SQLite 的父目录存在。"""
    if databaseUrl.get_backend_name() != "sqlite" or not databaseUrl.database:
        return
    if databaseUrl.database == ":memory:":
        return
    Path(databaseUrl.database).parent.mkdir(parents=True, exist_ok=True)


def runMigrationsOffline() -> None:
    """仅根据数据库 URL 生成离线迁移 SQL。"""
    context.configure(
        url=getDatabaseUrl(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def runMigrationsOnline() -> None:
    """通过短生命周期 Connection 执行在线迁移。"""
    databaseUrl = getDatabaseUrl()
    ensureSqliteDirectory(databaseUrl)
    connectable = create_engine(databaseUrl, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    runMigrationsOffline()
else:
    runMigrationsOnline()

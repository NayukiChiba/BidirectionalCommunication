"""
Alembic 迁移运行环境

每次执行 alembic upgrade、downgrade、check 或 revision --autogenerate，
Alembic 都会运行本文件。它使用短生命周期同步连接准备数据库和 ORM 元数据，
不属于应用运行时的异步数据库访问，也不启动 Web 应用。
"""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL, make_url

from src.adapters.database.migrationConfig import (
    createMigrationDatabaseUrl,
    createMigrationSqliteUrl,
)
from src.adapters.database.models import DatabaseBase
from src.config import DatabaseSettings

# context.config 是 Alembic 根据 alembic.ini 和 pyproject.toml 创建的配置对象。
config = context.config

# 将 alembic.ini 中的日志段交给 Python logging，输出迁移进度。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 会把数据库当前结构与这份 ORM 元数据进行比较。
target_metadata = DatabaseBase.metadata


def getDatabaseUrl() -> URL:
    """优先使用命令覆盖，否则读取统一 DATABASE_URL 配置。"""
    arguments = context.get_x_argument(as_dictionary=True)
    databaseUrl = arguments.get("database_url")
    if databaseUrl:
        return createMigrationDatabaseUrl(databaseUrl)

    # 保留 database_path 供现有 SQLite 学习实验使用。
    databasePath = arguments.get("database_path")
    if databasePath:
        return createMigrationSqliteUrl(Path(databasePath))

    # 第二优先级：测试通过 Config.set_main_option() 注入的完整数据库 URL。
    configuredUrl = config.get_main_option("sqlalchemy.url")
    if configuredUrl:
        return make_url(configuredUrl)

    configuredSettings = DatabaseSettings()
    return createMigrationDatabaseUrl(configuredSettings.databaseUrl.get_secret_value())


def ensureSqliteDirectory(databaseUrl: URL) -> None:
    """在线迁移前确保文件 SQLite 的父目录存在。"""
    # 其他数据库没有本地文件目录；SQLite 内存数据库也不需要创建目录。
    if databaseUrl.get_backend_name() != "sqlite" or not databaseUrl.database:
        return
    if databaseUrl.database == ":memory:":
        return
    Path(databaseUrl.database).parent.mkdir(parents=True, exist_ok=True)


def runMigrationsOffline() -> None:
    """不连接数据库，只把迁移渲染为 SQL 文本。"""
    # 离线模式由 `alembic upgrade head --sql` 使用。
    databaseUrl = getDatabaseUrl()
    context.configure(
        url=databaseUrl,
        # 提供 ORM 元数据，使 autogenerate/check 能理解目标结构。
        target_metadata=target_metadata,
        # 把参数值直接写入生成的 SQL，离线脚本不依赖运行时绑定参数。
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 检查字段类型变化，不只检查表和字段是否存在。
        compare_type=True,
        # 只有 SQLite 需要 batch 重建来兼容有限的 ALTER TABLE。
        render_as_batch=databaseUrl.get_backend_name() == "sqlite",
    )

    # 让 Alembic 建立迁移上下文并按 revision 顺序调用 upgrade/downgrade。
    with context.begin_transaction():
        context.run_migrations()


def runMigrationsOnline() -> None:
    """连接真实数据库并直接执行迁移。"""
    databaseUrl = getDatabaseUrl()
    ensureSqliteDirectory(databaseUrl)

    # 迁移命令运行时间短，NullPool 避免 CLI 结束后保留连接池资源。
    connectable = create_engine(databaseUrl, poolclass=pool.NullPool)

    # Connection 只在当前迁移命令期间存在，退出 with 后必定关闭。
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 与离线模式保持相同的类型比较和方言策略。
            compare_type=True,
            render_as_batch=databaseUrl.get_backend_name() == "sqlite",
        )

        # Alembic 根据 alembic_version 决定需要执行哪些 revision。
        with context.begin_transaction():
            context.run_migrations()


# --sql 使用离线模式；普通 upgrade、downgrade 和 check 使用在线模式。
if context.is_offline_mode():
    runMigrationsOffline()
else:
    runMigrationsOnline()

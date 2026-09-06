"""Alembic 同步迁移和结构检查使用的数据库配置。"""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url

from src.config import PROJECT_ROOT

MigrationTarget = Path | str | URL


def createMigrationSqliteUrl(databasePath: Path) -> URL:
    """为 Alembic 创建同步 pysqlite URL。"""
    resolvedPath = databasePath.expanduser().resolve()
    return URL.create("sqlite+pysqlite", database=str(resolvedPath))


def createMigrationDatabaseUrl(target: MigrationTarget) -> URL:
    """把路径或运行时 URL 转换为 Alembic 使用的同步 URL。"""
    if isinstance(target, Path):
        return createMigrationSqliteUrl(target)
    url = make_url(target) if isinstance(target, str) else target
    backend = url.get_backend_name()
    if backend == "sqlite":
        return url.set(drivername="sqlite+pysqlite")
    if backend == "postgresql":
        return url.set(drivername="postgresql+psycopg")
    raise ValueError(f"不支持的迁移数据库后端：{backend}")


def createMigrationEngine(target: MigrationTarget) -> Engine:
    """创建仅供迁移验证和同步结构检查使用的 Engine。"""
    databaseUrl = createMigrationDatabaseUrl(target)
    if databaseUrl.get_backend_name() == "sqlite" and databaseUrl.database:
        Path(databaseUrl.database).expanduser().resolve().parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    return create_engine(databaseUrl)


def createMigrationConfig(target: MigrationTarget) -> Config:
    """创建指向指定数据库且加载项目迁移目录的 Alembic 配置。"""
    alembicConfig = Config(
        file_=PROJECT_ROOT / "alembic.ini",
        toml_file=PROJECT_ROOT / "pyproject.toml",
    )
    databaseUrl = createMigrationDatabaseUrl(target).render_as_string(
        hide_password=False
    )
    alembicConfig.set_main_option(
        "sqlalchemy.url",
        databaseUrl.replace("%", "%%"),
    )
    return alembicConfig

"""Alembic 同步迁移和结构检查使用的隔离配置。"""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from src.config import PROJECT_ROOT


def createMigrationSqliteUrl(databasePath: Path) -> URL:
    """为 Alembic 创建同步 pysqlite URL。"""
    resolvedPath = databasePath.expanduser().resolve()
    return URL.create("sqlite+pysqlite", database=str(resolvedPath))


def createMigrationEngine(databasePath: Path) -> Engine:
    """创建仅供迁移验证和同步结构检查使用的 Engine。"""
    resolvedPath = databasePath.expanduser().resolve()
    resolvedPath.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(createMigrationSqliteUrl(resolvedPath))


def createMigrationConfig(databasePath: Path) -> Config:
    """创建指向指定 SQLite 文件且加载项目迁移目录的 Alembic 配置。"""
    alembicConfig = Config(
        file_=PROJECT_ROOT / "alembic.ini",
        toml_file=PROJECT_ROOT / "pyproject.toml",
    )
    databaseUrl = createMigrationSqliteUrl(databasePath).render_as_string(
        hide_password=False
    )
    alembicConfig.set_main_option(
        "sqlalchemy.url",
        databaseUrl.replace("%", "%%"),
    )
    return alembicConfig

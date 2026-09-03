"""为 CLI 之外的迁移调用创建隔离 Alembic 配置。"""

from pathlib import Path

from alembic.config import Config

from src.adapters.database.connection import createSqliteUrl
from src.config import PROJECT_ROOT


def createMigrationConfig(databasePath: Path) -> Config:
    """创建指向指定 SQLite 文件且加载项目迁移目录的 Alembic 配置。"""
    alembicConfig = Config(
        file_=PROJECT_ROOT / "alembic.ini",
        toml_file=PROJECT_ROOT / "pyproject.toml",
    )
    databaseUrl = createSqliteUrl(databasePath).render_as_string(hide_password=False)
    alembicConfig.set_main_option(
        "sqlalchemy.url",
        databaseUrl.replace("%", "%%"),
    )
    return alembicConfig

"""Alembic 消息表迁移集成测试。"""

import ast
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, text

from src.adapters.database import createSqliteEngine
from src.adapters.database.migrationConfig import createMigrationConfig
from src.config import PROJECT_ROOT

INITIAL_REVISION = "e5f06ff274b9"


def getCurrentRevision(databasePath: Path) -> str | None:
    """读取数据库记录的当前 Alembic revision。"""
    engine = createSqliteEngine(databasePath)
    try:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def getTableNames(databasePath: Path) -> set[str]:
    """返回指定 SQLite 数据库的全部表名。"""
    engine = createSqliteEngine(databasePath)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_empty_database_to_head(tmp_path: Path) -> None:
    """全新数据库应升级到当前消息表结构和版本。"""
    databasePath = tmp_path / "empty.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)

    command.upgrade(migrationConfig, "head")

    assert getTableNames(databasePath) == {"alembic_version", "messages"}
    assert getCurrentRevision(databasePath) == INITIAL_REVISION


def test_downgrade_then_upgrade_restores_target_schema(tmp_path: Path) -> None:
    """降级到 base 后再次升级应恢复最新结构。"""
    databasePath = tmp_path / "round-trip.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)
    command.upgrade(migrationConfig, "head")

    command.downgrade(migrationConfig, "base")

    assert getTableNames(databasePath) == {"alembic_version"}
    assert getCurrentRevision(databasePath) is None

    command.upgrade(migrationConfig, "head")

    assert getTableNames(databasePath) == {"alembic_version", "messages"}
    assert getCurrentRevision(databasePath) == INITIAL_REVISION


def test_migration_history_matches_orm_metadata(tmp_path: Path) -> None:
    """升级到 head 后不应存在未生成的 ORM 结构差异。"""
    databasePath = tmp_path / "metadata-check.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)
    command.upgrade(migrationConfig, "head")

    command.check(migrationConfig)


def test_migration_scripts_do_not_import_web_runtime() -> None:
    """迁移环境不能依赖运行中的 Web 服务或组合根。"""
    migrationFiles = [
        PROJECT_ROOT / "migrations" / "env.py",
        *(PROJECT_ROOT / "migrations" / "versions").glob("*.py"),
    ]
    forbiddenModules = {"bootstrap", "fastapi", "main", "starlette"}

    for filepath in migrationFiles:
        syntaxTree = ast.parse(filepath.read_text(encoding="utf-8"))
        importedModules = {
            node.module.split(".", maxsplit=1)[0]
            for node in ast.walk(syntaxTree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        importedModules.update(
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(syntaxTree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert importedModules.isdisjoint(forbiddenModules)

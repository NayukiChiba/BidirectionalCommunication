"""Alembic 消息表迁移集成测试。"""

import ast
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, text

from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)
from src.config import PROJECT_ROOT

HEAD_REVISION = "c18a4f7d2e91"


def getCurrentRevision(databasePath: Path) -> str | None:
    """读取数据库记录的当前 Alembic revision。"""
    engine = createMigrationEngine(databasePath)
    try:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def getTableNames(databasePath: Path) -> set[str]:
    """返回指定 SQLite 数据库的全部表名。"""
    engine = createMigrationEngine(databasePath)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_empty_database_to_head(tmp_path: Path) -> None:
    """全新数据库应升级到当前消息表结构和版本。"""
    databasePath = tmp_path / "empty.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)

    command.upgrade(migrationConfig, "head")

    assert getTableNames(databasePath) == {
        "alembic_version",
        "messages",
        "users",
        "conversations",
        "conversation_members",
    }
    assert getCurrentRevision(databasePath) == HEAD_REVISION


def test_downgrade_then_upgrade_restores_target_schema(tmp_path: Path) -> None:
    """降级到 base 后再次升级应恢复最新结构。"""
    databasePath = tmp_path / "round-trip.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)
    command.upgrade(migrationConfig, "head")

    command.downgrade(migrationConfig, "base")

    assert getTableNames(databasePath) == {"alembic_version"}
    assert getCurrentRevision(databasePath) is None

    command.upgrade(migrationConfig, "head")

    assert getTableNames(databasePath) == {
        "alembic_version",
        "messages",
        "users",
        "conversations",
        "conversation_members",
    }
    assert getCurrentRevision(databasePath) == HEAD_REVISION


def test_migration_history_matches_orm_metadata(tmp_path: Path) -> None:
    """升级到 head 后不应存在未生成的 ORM 结构差异。"""
    databasePath = tmp_path / "metadata-check.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)
    command.upgrade(migrationConfig, "head")

    command.check(migrationConfig)


def test_conversation_migration_backfills_existing_bidirectional_messages(
    tmp_path: Path,
) -> None:
    """旧双向消息应归入同一个稳定会话并生成两个成员。"""
    databasePath = tmp_path / "backfill.sqlite3"
    migrationConfig = createMigrationConfig(databasePath)
    command.upgrade(migrationConfig, "f53ad4a832a9")
    firstUserId = "10000000-0000-0000-0000-000000000001"
    secondUserId = "20000000-0000-0000-0000-000000000002"
    engine = createMigrationEngine(databasePath)
    try:
        with engine.begin() as connection:
            for userId, username in (
                (firstUserId, "user-a"),
                (secondUserId, "user-b"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(user_id, username, password_hash, created_at) "
                        "VALUES (:userId, :username, 'test-hash', :createdAt)"
                    ),
                    {
                        "userId": userId,
                        "username": username,
                        "createdAt": "2026-09-04 12:00:00",
                    },
                )
            for sequence, senderId, recipientId in (
                (1, firstUserId, secondUserId),
                (2, secondUserId, firstUserId),
            ):
                connection.execute(
                    text(
                        "INSERT INTO messages "
                        "(message_id, client_message_id, sender_id, recipient_id, "
                        "content, created_at) VALUES (:messageId, :clientMessageId, "
                        ":senderId, :recipientId, :content, :createdAt)"
                    ),
                    {
                        "messageId": f"{sequence:08d}-0000-0000-0000-000000000000",
                        "clientMessageId": (
                            f"{sequence + 10:08d}-0000-0000-0000-000000000000"
                        ),
                        "senderId": senderId,
                        "recipientId": recipientId,
                        "content": f"message-{sequence}",
                        "createdAt": f"2026-09-04 12:00:0{sequence}",
                    },
                )
    finally:
        engine.dispose()

    command.upgrade(migrationConfig, "head")

    engine = createMigrationEngine(databasePath)
    try:
        with engine.connect() as connection:
            conversationCount = connection.scalar(
                text("SELECT COUNT(*) FROM conversations")
            )
            memberCount = connection.scalar(
                text("SELECT COUNT(*) FROM conversation_members")
            )
            conversationIds = (
                connection.execute(
                    text("SELECT DISTINCT conversation_id FROM messages")
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()

    assert conversationCount == 1
    assert memberCount == 2
    assert len(conversationIds) == 1


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

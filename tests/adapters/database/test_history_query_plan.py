"""SQLite 单聊历史查询计划测试。"""

from pathlib import Path

from alembic import command
from sqlalchemy import text

from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)


def test_conversation_history_query_uses_expected_composite_index(
    tmp_path: Path,
) -> None:
    """双向单聊 OR 查询的两个分支都应复用同一复合索引。"""
    databasePath = tmp_path / "query-plan.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createMigrationEngine(databasePath)

    try:
        with engine.connect() as connection:
            planRows = connection.execute(
                text(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT *
                    FROM messages
                    WHERE conversation_id = :conversationId
                    AND (
                        created_at > :createdAt
                        OR (created_at = :createdAt AND message_id > :messageId)
                    )
                    ORDER BY created_at, message_id
                    LIMIT :limit
                    """
                ),
                {
                    "conversationId": "90000000-0000-0000-0000-000000000009",
                    "createdAt": "2026-09-03 12:00:00",
                    "messageId": "00000000-0000-0000-0000-000000000000",
                    "limit": 51,
                },
            ).all()
    finally:
        engine.dispose()

    planDescription = "\n".join(str(row[3]) for row in planRows)
    assert "ix_messages_conversation_created_message" in planDescription
    assert "SCAN messages" not in planDescription

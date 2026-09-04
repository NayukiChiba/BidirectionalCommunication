"""Conversation 聚合 Repository、约束和并发创建集成测试。"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.adapters.database import (
    AsyncSqlAlchemyConversationUnitOfWorkFactory,
    AsyncSqlAlchemyUserUnitOfWorkFactory,
    ConversationMemberRecord,
    ConversationRecord,
    UserRecord,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
)
from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)
from src.application import (
    CreateConversationCommand,
    CreateConversationService,
)


@pytest_asyncio.fixture
async def sessionFactory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """创建已经迁移并包含两个注册用户的异步数据库。"""
    databasePath = tmp_path / "conversations.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine: AsyncEngine = createAsyncSqliteEngine(databasePath)
    factory = createAsyncSessionFactory(engine)
    now = datetime.now(timezone.utc)
    async with factory.begin() as session:
        session.add_all(
            [
                UserRecord(
                    userId=str(uuid4()),
                    username="user-a",
                    passwordHash="test-hash",
                    createdAt=now,
                ),
                UserRecord(
                    userId=str(uuid4()),
                    username="user-b",
                    passwordHash="test-hash",
                    createdAt=now,
                ),
            ]
        )
    try:
        yield factory
    finally:
        await engine.dispose()


async def getUserIds(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    """按用户名顺序读取测试用户 ID。"""
    async with sessionFactory() as session:
        ids = (
            await session.scalars(
                select(UserRecord.userId).order_by(UserRecord.username)
            )
        ).all()
    return ids[0], ids[1]


def test_conversation_tables_express_member_constraints(tmp_path: Path) -> None:
    """会话身份、成员外键、去重和两个槽位应由数据库结构保护。"""
    databasePath = tmp_path / "conversation-schema.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createMigrationEngine(databasePath)
    try:
        inspector = inspect(engine)
        conversationUnique = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("conversations")
        }
        memberUnique = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("conversation_members")
        }
        memberForeignKeys = {
            (tuple(key["constrained_columns"]), key["referred_table"])
            for key in inspector.get_foreign_keys("conversation_members")
        }
        memberChecks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("conversation_members")
        }
    finally:
        engine.dispose()

    assert conversationUnique == {("member_pair_key",)}
    assert memberUnique == {("conversation_id", "member_position")}
    assert memberForeignKeys == {
        (("conversation_id",), "conversations"),
        (("user_id",), "users"),
    }
    assert memberChecks == {"ck_conversation_members_position"}


@pytest.mark.asyncio
async def test_concurrent_create_or_get_returns_one_conversation(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """两个并发方向请求由数据库唯一约束收敛为同一个会话。"""
    userAId, userBId = await getUserIds(sessionFactory)
    service = CreateConversationService(
        AsyncSqlAlchemyConversationUnitOfWorkFactory(sessionFactory),
        AsyncSqlAlchemyUserUnitOfWorkFactory(sessionFactory),
    )

    results = await asyncio.gather(
        service.createOrGet(CreateConversationCommand(userAId, userBId)),
        service.createOrGet(CreateConversationCommand(userBId, userAId)),
    )

    assert {str(result.conversation.conversation_id) for result in results} == {
        str(results[0].conversation.conversation_id)
    }
    assert sorted(result.created for result in results) == [False, True]
    async with sessionFactory() as session:
        conversationCount = await session.scalar(
            select(func.count()).select_from(ConversationRecord)
        )
        memberCount = await session.scalar(
            select(func.count()).select_from(ConversationMemberRecord)
        )
    assert conversationCount == 1
    assert memberCount == 2

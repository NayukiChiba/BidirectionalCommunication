"""Conversation 聚合 Repository、约束和并发创建集成测试。"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
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
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    MessageContent,
    MessageId,
    MessagePosition,
    UserId,
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
        (("delivered_message_id",), "messages"),
        (("read_message_id",), "messages"),
        (("user_id",), "users"),
    }
    assert memberChecks == {
        "ck_conversation_members_delivered_pair",
        "ck_conversation_members_position",
        "ck_conversation_members_read_pair",
    }


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


@pytest.mark.asyncio
async def test_concurrent_delivery_updates_cannot_move_position_backwards(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """较旧确认晚提交时也不能覆盖已经前进的累计送达位置。"""
    userAId, userBId = await getUserIds(sessionFactory)
    unitOfWorkFactory = AsyncSqlAlchemyConversationUnitOfWorkFactory(sessionFactory)
    service = CreateConversationService(
        unitOfWorkFactory,
        AsyncSqlAlchemyUserUnitOfWorkFactory(sessionFactory),
    )
    conversation = (
        await service.createOrGet(CreateConversationCommand(userAId, userBId))
    ).conversation
    baseTime = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)
    messages = tuple(
        ChatMessage(
            message_id=MessageId(uuid4()),
            client_message_id=ClientMessageId(uuid4()),
            conversation_id=conversation.conversation_id,
            sender_id=UserId(userAId),
            recipient_id=UserId(userBId),
            content=MessageContent(f"message-{sequence}"),
            created_at=baseTime + timedelta(seconds=sequence),
        )
        for sequence in (1, 2)
    )
    async with unitOfWorkFactory() as unitOfWork:
        for message in messages:
            await unitOfWork.messages.add(message)
        await unitOfWork.commit()

    async def advance(message: ChatMessage) -> bool:
        """在独立事务中提交一个候选累计位置。"""
        async with unitOfWorkFactory() as unitOfWork:
            advanced = await unitOfWork.progress.advanceDelivered(
                conversation.conversation_id,
                UserId(userBId),
                MessagePosition(message.created_at, message.message_id),
            )
            await unitOfWork.commit()
            return advanced

    await asyncio.gather(advance(messages[1]), advance(messages[0]))

    async with unitOfWorkFactory() as unitOfWork:
        progress = await unitOfWork.progress.get(
            ConversationId(conversation.conversation_id.value),
            UserId(userBId),
        )
    assert progress is not None
    assert progress.delivered_position == MessagePosition(
        messages[1].created_at,
        messages[1].message_id,
    )

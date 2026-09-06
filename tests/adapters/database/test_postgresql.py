"""真实 PostgreSQL 迁移、Repository、并发和事务语义测试。"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.adapters.database import (
    AsyncSqlAlchemyConversationUnitOfWorkFactory,
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
    AsyncSqlAlchemyUserUnitOfWorkFactory,
    createAsyncDatabaseEngine,
    createAsyncSessionFactory,
)
from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)
from src.adapters.database.models import UserRecord
from src.application import (
    CreateConversationCommand,
    CreateConversationService,
    MessageCursor,
    MessageStorageConflictError,
)
from src.domain import (
    ChatMessage,
    ClientMessageId,
    Conversation,
    MessageContent,
    MessageId,
    UserId,
    create_chat_message,
)


@pytest.fixture(scope="module")
def postgresDatabaseUrl() -> Iterator[str]:
    """重建显式测试数据库结构，未配置服务时只跳过本模块。"""
    databaseUrl = os.getenv("TEST_POSTGRES_URL")
    if not databaseUrl:
        pytest.skip("未设置 TEST_POSTGRES_URL，跳过 PostgreSQL 集成测试")
    migrationConfig = createMigrationConfig(databaseUrl)
    command.downgrade(migrationConfig, "base")
    command.upgrade(migrationConfig, "head")
    try:
        yield databaseUrl
    finally:
        command.downgrade(migrationConfig, "base")


@pytest_asyncio.fixture
async def postgresEngine(
    postgresDatabaseUrl: str,
) -> AsyncIterator[AsyncEngine]:
    """创建使用真实 asyncpg 异步连接池的 Engine。"""
    engine = createAsyncDatabaseEngine(
        postgresDatabaseUrl,
        poolSize=3,
        maxOverflow=2,
        poolTimeoutSeconds=5,
        poolRecycleSeconds=600,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def postgresSessionFactory(
    postgresEngine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建 PostgreSQL Repository 共用的 AsyncSession 工厂。"""
    return createAsyncSessionFactory(postgresEngine)


async def addUsers(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> tuple[UserId, UserId]:
    """向真实 PostgreSQL 添加两个唯一测试用户。"""
    firstUserId = UserId(str(uuid4()))
    secondUserId = UserId(str(uuid4()))
    now = datetime.now(timezone.utc)
    async with sessionFactory.begin() as session:
        session.add_all(
            [
                UserRecord(
                    userId=str(firstUserId),
                    username=f"pg-a-{uuid4().hex[:12]}",
                    passwordHash="postgres-test-hash",
                    createdAt=now,
                ),
                UserRecord(
                    userId=str(secondUserId),
                    username=f"pg-b-{uuid4().hex[:12]}",
                    passwordHash="postgres-test-hash",
                    createdAt=now,
                ),
            ]
        )
    return firstUserId, secondUserId


async def createStoredConversation(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> tuple[Conversation, UserId, UserId]:
    """通过真实应用服务创建会话并返回成员。"""
    firstUserId, secondUserId = await addUsers(sessionFactory)
    service = CreateConversationService(
        AsyncSqlAlchemyConversationUnitOfWorkFactory(sessionFactory),
        AsyncSqlAlchemyUserUnitOfWorkFactory(sessionFactory),
    )
    result = await service.createOrGet(
        CreateConversationCommand(str(firstUserId), str(secondUserId))
    )
    return result.conversation, firstUserId, secondUserId


def test_all_migrations_and_metadata_match_postgresql(
    postgresDatabaseUrl: str,
) -> None:
    """空 PostgreSQL 数据库应执行全部迁移且与 ORM 元数据一致。"""
    command.check(createMigrationConfig(postgresDatabaseUrl))
    engine = createMigrationEngine(postgresDatabaseUrl)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "conversation_members",
            "conversations",
            "messages",
            "users",
        }
        createdAt = next(
            column
            for column in inspector.get_columns("messages")
            if column["name"] == "created_at"
        )
        assert createdAt["type"].timezone is True
        indexes = {index["name"] for index in inspector.get_indexes("messages")}
        assert "ix_messages_conversation_created_message" in indexes
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_uses_read_committed_and_configured_pool(
    postgresEngine: AsyncEngine,
) -> None:
    """连接应使用默认 READ COMMITTED 和有界健康连接池。"""
    async with postgresEngine.connect() as connection:
        isolationLevel = await connection.get_isolation_level()

    assert isolationLevel == "READ COMMITTED"
    assert postgresEngine.pool.size() == 3
    assert postgresEngine.pool._max_overflow == 2
    assert postgresEngine.pool._pre_ping is True


@pytest.mark.asyncio
async def test_read_committed_hides_uncommitted_rows_then_refreshes_snapshot(
    postgresSessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """READ COMMITTED 每条语句只读取当时已经提交的数据。"""
    userId = str(uuid4())
    username = f"isolation-{uuid4().hex[:12]}"
    record = UserRecord(
        userId=userId,
        username=username,
        passwordHash="postgres-test-hash",
        createdAt=datetime.now(timezone.utc),
    )
    statement = select(UserRecord).where(UserRecord.userId == userId)

    async with postgresSessionFactory() as writerSession:
        async with postgresSessionFactory() as readerSession:
            writerSession.add(record)
            await writerSession.flush()

            beforeCommit = (await readerSession.scalars(statement)).one_or_none()
            await writerSession.commit()
            afterCommit = (await readerSession.scalars(statement)).one_or_none()

    assert beforeCommit is None
    assert afterCommit is not None


@pytest.mark.asyncio
async def test_message_repository_preserves_utc_and_stable_cursor_order(
    postgresSessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """PostgreSQL 时区和相同时间消息分页应与 Repository 契约一致。"""
    conversation, firstUserId, secondUserId = await createStoredConversation(
        postgresSessionFactory
    )
    createdAt = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    messages = tuple(
        ChatMessage(
            message_id=MessageId(UUID(int=sequence)),
            client_message_id=ClientMessageId(uuid4()),
            conversation_id=conversation.conversation_id,
            sender_id=firstUserId,
            recipient_id=secondUserId,
            content=MessageContent(f"postgres-message-{sequence}"),
            created_at=createdAt,
        )
        for sequence in (3, 1, 2)
    )
    unitOfWorkFactory = AsyncSqlAlchemyMessageUnitOfWorkFactory(postgresSessionFactory)
    async with unitOfWorkFactory() as unitOfWork:
        for message in messages:
            await unitOfWork.messages.add(message)
        await unitOfWork.commit()

    async with unitOfWorkFactory() as unitOfWork:
        firstPage = await unitOfWork.messages.listByConversation(
            conversation.conversation_id,
            cursor=None,
            limit=2,
        )
        secondPage = await unitOfWork.messages.listByConversation(
            conversation.conversation_id,
            cursor=MessageCursor.fromMessage(firstPage[-1]),
            limit=2,
        )

    assert [message.message_id.value.int for message in firstPage] == [1, 2]
    assert [message.message_id.value.int for message in secondPage] == [3]
    assert all(message.created_at.tzinfo is timezone.utc for message in firstPage)


@pytest.mark.asyncio
async def test_postgresql_unique_constraint_guards_concurrent_idempotency(
    postgresSessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """并发相同客户端消息键只能在 PostgreSQL 中提交一条。"""
    conversation, firstUserId, secondUserId = await createStoredConversation(
        postgresSessionFactory
    )
    clientMessageId = ClientMessageId(uuid4())
    messages = tuple(
        create_chat_message(
            client_message_id=clientMessageId,
            conversation_id=conversation.conversation_id,
            sender_id=firstUserId,
            recipient_id=secondUserId,
            content=MessageContent(f"candidate-{sequence}"),
        )
        for sequence in (1, 2)
    )
    unitOfWorkFactory = AsyncSqlAlchemyMessageUnitOfWorkFactory(postgresSessionFactory)

    async def commitCandidate(message: ChatMessage) -> str:
        try:
            async with unitOfWorkFactory() as unitOfWork:
                await unitOfWork.messages.add(message)
                await unitOfWork.commit()
        except MessageStorageConflictError:
            return "conflict"
        return "committed"

    results = await asyncio.gather(*(commitCandidate(message) for message in messages))

    assert sorted(results) == ["committed", "conflict"]
    async with unitOfWorkFactory() as unitOfWork:
        stored = await unitOfWork.messages.getByClientMessageId(
            firstUserId,
            clientMessageId,
        )
    assert stored in messages


@pytest.mark.asyncio
async def test_postgresql_concurrent_conversation_creation_is_idempotent(
    postgresSessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """成员组合唯一约束应使并发反向创建返回同一会话。"""
    firstUserId, secondUserId = await addUsers(postgresSessionFactory)
    service = CreateConversationService(
        AsyncSqlAlchemyConversationUnitOfWorkFactory(postgresSessionFactory),
        AsyncSqlAlchemyUserUnitOfWorkFactory(postgresSessionFactory),
    )

    results = await asyncio.gather(
        service.createOrGet(
            CreateConversationCommand(str(firstUserId), str(secondUserId))
        ),
        service.createOrGet(
            CreateConversationCommand(str(secondUserId), str(firstUserId))
        ),
    )

    assert len({str(result.conversation.conversation_id) for result in results}) == 1
    assert sorted(result.created for result in results) == [False, True]

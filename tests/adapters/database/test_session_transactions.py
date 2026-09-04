"""AsyncSession 提交、回滚和关闭行为集成测试。"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from src.adapters.database import (
    ConversationRecord,
    MessageRecord,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
    toDomainMessage,
    toMessageRecord,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.domain import (
    ClientMessageId,
    ConversationId,
    MessageContent,
    UserId,
    create_chat_message,
)

TEST_CONVERSATION_ID = UUID("90000000-0000-0000-0000-000000000009")


@pytest_asyncio.fixture
async def databaseEngine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """创建使用临时文件的 AsyncEngine。"""
    databasePath = tmp_path / "nested" / "messages.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createAsyncSqliteEngine(databasePath)
    sessionFactory = createAsyncSessionFactory(engine)
    async with sessionFactory.begin() as session:
        session.add(
            ConversationRecord(
                conversationId=str(TEST_CONVERSATION_ID),
                memberPairKey="sender-a:recipient-b",
                createdAt=datetime.now(timezone.utc),
            )
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def sessionFactory(
    databaseEngine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建绑定测试 AsyncEngine 的 AsyncSession 工厂。"""
    return createAsyncSessionFactory(databaseEngine)


def createRecord(
    *,
    senderId: str = "sender-a",
    clientMessageId: UUID | None = None,
) -> MessageRecord:
    """创建可持久化的消息记录。"""
    message = create_chat_message(
        client_message_id=ClientMessageId(
            clientMessageId if clientMessageId is not None else uuid4()
        ),
        conversation_id=ConversationId(TEST_CONVERSATION_ID),
        sender_id=UserId(senderId),
        recipient_id=UserId("recipient-b"),
        content=MessageContent("事务测试消息"),
    )
    return toMessageRecord(message)


@pytest.mark.asyncio
async def test_async_engine_uses_configured_path_and_connection_closes(
    tmp_path: Path,
) -> None:
    """AsyncEngine 应使用 aiosqlite URL，AsyncConnection 应异步关闭。"""
    databasePath = tmp_path / "nested" / "configured.sqlite3"
    engine = createAsyncSqliteEngine(databasePath)
    try:
        assert Path(engine.url.database or "") == databasePath.resolve()
        assert engine.url.drivername == "sqlite+aiosqlite"
        assert databasePath.parent.is_dir()

        connection = await engine.connect()
        assert not connection.closed
        await connection.close()
        assert connection.closed
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_is_visible_to_a_new_async_session(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """提交后的记录应能被新 AsyncSession 查询。"""
    record = createRecord()
    messageId = record.messageId

    async with sessionFactory() as session:
        session.add(record)
        await session.flush()
        assert inspect(record).persistent
        await session.commit()

    async with sessionFactory() as session:
        statement = select(MessageRecord).where(MessageRecord.messageId == messageId)
        persistedRecord = (await session.scalars(statement)).one()
        persistedMessage = toDomainMessage(persistedRecord)

    assert str(persistedMessage.message_id) == messageId
    assert persistedMessage.created_at.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_rollback_is_not_visible_to_a_new_async_session(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """刷新后回滚的记录不应被新 AsyncSession 查询。"""
    record = createRecord()

    async with sessionFactory() as session:
        session.add(record)
        await session.flush()
        await session.rollback()

    async with sessionFactory() as session:
        statement = select(MessageRecord).where(
            MessageRecord.messageId == record.messageId
        )
        assert (await session.scalars(statement)).one_or_none() is None


@pytest.mark.asyncio
async def test_close_rolls_back_transaction_and_detaches_record(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """关闭 AsyncSession 应释放对象并回滚尚未提交的事务。"""
    record = createRecord()
    session = sessionFactory()
    session.add(record)
    await session.flush()

    await session.close()

    assert inspect(record).detached
    async with sessionFactory() as verificationSession:
        statement = select(MessageRecord).where(
            MessageRecord.messageId == record.messageId
        )
        assert (await verificationSession.scalars(statement)).one_or_none() is None


@pytest.mark.asyncio
async def test_sender_and_client_message_id_are_unique_together(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """同一发送者不能重复保存相同客户端消息标识。"""
    clientMessageId = uuid4()
    firstRecord = createRecord(clientMessageId=clientMessageId)
    duplicateRecord = createRecord(clientMessageId=clientMessageId)

    async with sessionFactory() as session:
        session.add(firstRecord)
        await session.commit()

    async with sessionFactory() as session:
        session.add(duplicateRecord)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

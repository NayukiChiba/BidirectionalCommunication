"""异步 SQLAlchemy 消息 Repository 与 Unit of Work 集成测试。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from src.adapters.database import (
    AsyncSqlAlchemyMessageUnitOfWork,
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
    MessageRecord,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.application import MessageStorageConflictError
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)
from src.domain import create_chat_message as createChatMessage


@pytest_asyncio.fixture
async def databaseEngine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """创建具有消息表的临时 AsyncEngine。"""
    databasePath = tmp_path / "unit-of-work.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createAsyncSqliteEngine(databasePath)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def sessionFactory(
    databaseEngine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建测试使用的 AsyncSession 工厂。"""
    return createAsyncSessionFactory(databaseEngine)


def createMessage(*, messageId: UUID, clientMessageId: UUID) -> ChatMessage:
    """创建可以控制服务端和客户端标识的领域消息。"""
    message = createChatMessage(
        client_message_id=ClientMessageId(clientMessageId),
        sender_id=UserId("duplicate-sender"),
        recipient_id=UserId("recipient"),
        content=MessageContent("提交失败测试"),
    )
    return ChatMessage(
        message_id=MessageId(messageId),
        client_message_id=message.client_message_id,
        sender_id=message.sender_id,
        recipient_id=message.recipient_id,
        content=message.content,
        created_at=message.created_at,
    )


async def countMessages(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> int:
    """通过新 AsyncSession 统计已提交消息数。"""
    async with sessionFactory() as session:
        return (
            await session.scalar(select(func.count()).select_from(MessageRecord)) or 0
        )


@pytest.mark.asyncio
async def test_commit_failure_is_translated_and_session_remains_usable(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """约束导致的提交失败应转换异常、回滚并关闭失败 AsyncSession。"""
    firstMessage = createMessage(
        messageId=UUID("10000000-0000-0000-0000-000000000001"),
        clientMessageId=UUID("20000000-0000-0000-0000-000000000002"),
    )
    duplicateMessage = createMessage(
        messageId=UUID("30000000-0000-0000-0000-000000000003"),
        clientMessageId=UUID("20000000-0000-0000-0000-000000000002"),
    )
    unitOfWorkFactory = AsyncSqlAlchemyMessageUnitOfWorkFactory(sessionFactory)

    async with unitOfWorkFactory() as unitOfWork:
        await unitOfWork.messages.add(firstMessage)
        await unitOfWork.commit()

    with pytest.raises(MessageStorageConflictError):
        async with unitOfWorkFactory() as unitOfWork:
            await unitOfWork.messages.add(duplicateMessage)
            await unitOfWork.commit()

    assert await countMessages(sessionFactory) == 1

    # 提交失败的 AsyncSession 已关闭，后续工作单元仍能独立使用。
    thirdMessage = createMessage(
        messageId=UUID("40000000-0000-0000-0000-000000000004"),
        clientMessageId=UUID("50000000-0000-0000-0000-000000000005"),
    )
    async with unitOfWorkFactory() as unitOfWork:
        await unitOfWork.messages.add(thirdMessage)
        await unitOfWork.commit()

    assert await countMessages(sessionFactory) == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_commits_create_only_one_message(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """并发写入相同幂等键时数据库唯一约束必须只接受一条。"""
    clientMessageId = UUID("60000000-0000-0000-0000-000000000006")
    messages = (
        createMessage(
            messageId=UUID("70000000-0000-0000-0000-000000000007"),
            clientMessageId=clientMessageId,
        ),
        createMessage(
            messageId=UUID("80000000-0000-0000-0000-000000000008"),
            clientMessageId=clientMessageId,
        ),
    )
    unitOfWorkFactory = AsyncSqlAlchemyMessageUnitOfWorkFactory(sessionFactory)

    async def commitMessage(message: ChatMessage) -> str:
        """在独立 Task 和工作单元中提交一条候选消息。"""
        try:
            async with unitOfWorkFactory() as unitOfWork:
                await unitOfWork.messages.add(message)
                await unitOfWork.commit()
        except MessageStorageConflictError:
            return "conflict"
        return "committed"

    results = await asyncio.gather(*(commitMessage(message) for message in messages))

    assert sorted(results) == ["committed", "conflict"]
    assert await countMessages(sessionFactory) == 1

    async with unitOfWorkFactory() as unitOfWork:
        persistedMessage = await unitOfWork.messages.getByClientMessageId(
            UserId("duplicate-sender"),
            ClientMessageId(clientMessageId),
        )

    assert persistedMessage in messages


@pytest.mark.asyncio
async def test_concurrent_tasks_receive_distinct_async_sessions(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> None:
    """并发 Task 必须各自持有并最终关闭独立 AsyncSession。"""
    unitOfWorkFactory = AsyncSqlAlchemyMessageUnitOfWorkFactory(sessionFactory)
    bothEntered = asyncio.Event()
    enteredUnits: list[AsyncSqlAlchemyMessageUnitOfWork] = []

    async def useSession() -> int:
        """进入工作单元，等待另一 Task 后执行一次显式查询。"""
        unitOfWork = unitOfWorkFactory()
        enteredUnits.append(unitOfWork)
        async with unitOfWork:
            sessionId = id(unitOfWork._requireSession())
            if len(enteredUnits) == 2:
                bothEntered.set()
            await bothEntered.wait()
            await unitOfWork.messages.getByClientMessageId(
                UserId("task-user"),
                ClientMessageId(UUID(int=sessionId)),
            )
            return sessionId

    sessionIds = await asyncio.gather(useSession(), useSession())

    assert len(set(sessionIds)) == 2
    assert all(unitOfWork._session is None for unitOfWork in enteredUnits)

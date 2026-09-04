"""内存与异步 SQLAlchemy 消息工作单元的共同契约测试。"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters import InMemoryMessageUnitOfWorkFactory
from src.adapters.database import (
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
    ConversationRecord,
    MessageRecord,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
    toDomainMessage,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.application import MessageCursor, MessageUnitOfWorkFactory
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    MessageContent,
    MessageId,
    UserId,
)
from src.domain import create_chat_message as createChatMessage

TEST_CONVERSATION_ID = UUID("90000000-0000-0000-0000-000000000009")


@dataclass(frozen=True, slots=True)
class UnitOfWorkBackend:
    """供共同契约读取已提交状态的测试后端。"""

    factory: MessageUnitOfWorkFactory
    loadMessages: Callable[[], Awaitable[tuple[ChatMessage, ...]]]


@pytest_asyncio.fixture(params=("memory", "sqlalchemy"))
async def unitOfWorkBackend(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[UnitOfWorkBackend]:
    """为相同异步契约提供内存和 SQLite 两种后端。"""
    if request.param == "memory":
        factory = InMemoryMessageUnitOfWorkFactory()

        async def loadMemoryMessages() -> tuple[ChatMessage, ...]:
            return factory.messages

        yield UnitOfWorkBackend(factory=factory, loadMessages=loadMemoryMessages)
        return

    databasePath = tmp_path / "contract.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createAsyncSqliteEngine(databasePath)
    sessionFactory = createAsyncSessionFactory(engine)
    async with sessionFactory.begin() as session:
        session.add(
            ConversationRecord(
                conversationId=str(TEST_CONVERSATION_ID),
                memberPairKey="contract-sender:contract-recipient",
                createdAt=datetime.now(timezone.utc),
            )
        )
        session.add(
            ConversationRecord(
                conversationId="80000000-0000-0000-0000-000000000008",
                memberPairKey="contract-sender:unrelated-user",
                createdAt=datetime.now(timezone.utc),
            )
        )

    async def loadDatabaseMessages() -> tuple[ChatMessage, ...]:
        return await loadSqlAlchemyMessages(sessionFactory)

    try:
        yield UnitOfWorkBackend(
            factory=AsyncSqlAlchemyMessageUnitOfWorkFactory(sessionFactory),
            loadMessages=loadDatabaseMessages,
        )
    finally:
        await engine.dispose()


def createMessage(content: str = "契约测试消息") -> ChatMessage:
    """创建共同契约使用的领域消息。"""
    return createChatMessage(
        client_message_id=ClientMessageId(uuid4()),
        conversation_id=ConversationId(TEST_CONVERSATION_ID),
        sender_id=UserId("contract-sender"),
        recipient_id=UserId("contract-recipient"),
        content=MessageContent(content),
    )


def createFixedMessage(
    *,
    messageSequence: int,
    senderId: str,
    recipientId: str,
    createdAt: datetime,
) -> ChatMessage:
    """创建具有固定排序字段的共同契约消息。"""
    return ChatMessage(
        message_id=MessageId(UUID(int=messageSequence)),
        client_message_id=ClientMessageId(UUID(int=messageSequence + 100)),
        conversation_id=ConversationId(
            TEST_CONVERSATION_ID
            if recipientId != "unrelated-user"
            else UUID("80000000-0000-0000-0000-000000000008")
        ),
        sender_id=UserId(senderId),
        recipient_id=UserId(recipientId),
        content=MessageContent(f"message-{messageSequence}"),
        created_at=createdAt,
    )


async def loadSqlAlchemyMessages(
    sessionFactory: async_sessionmaker[AsyncSession],
) -> tuple[ChatMessage, ...]:
    """从新 AsyncSession 加载所有已提交消息。"""
    async with sessionFactory() as session:
        records = (
            await session.scalars(
                select(MessageRecord).order_by(MessageRecord.createdAt)
            )
        ).all()
        return tuple(toDomainMessage(record) for record in records)


@pytest.mark.asyncio
async def test_committed_message_is_persisted(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现都必须持久化显式提交的消息。"""
    message = createMessage()

    async with unitOfWorkBackend.factory() as unitOfWork:
        await unitOfWork.messages.add(message)
        await unitOfWork.commit()

    assert await unitOfWorkBackend.loadMessages() == (message,)


@pytest.mark.asyncio
async def test_uncommitted_message_is_rolled_back(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现退出时都必须回滚未提交消息。"""
    async with unitOfWorkBackend.factory() as unitOfWork:
        await unitOfWork.messages.add(createMessage())

    assert await unitOfWorkBackend.loadMessages() == ()


@pytest.mark.asyncio
async def test_exception_rolls_back_message(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现遇到异常时都必须回滚并传播异常。"""
    with pytest.raises(RuntimeError, match="模拟用例异常"):
        async with unitOfWorkBackend.factory() as unitOfWork:
            await unitOfWork.messages.add(createMessage())
            raise RuntimeError("模拟用例异常")

    assert await unitOfWorkBackend.loadMessages() == ()


@pytest.mark.asyncio
async def test_get_by_sender_and_client_message_id(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种 Repository 都应按完整幂等键返回原消息。"""
    message = createMessage()
    async with unitOfWorkBackend.factory() as unitOfWork:
        await unitOfWork.messages.add(message)
        await unitOfWork.commit()

    async with unitOfWorkBackend.factory() as unitOfWork:
        foundMessage = await unitOfWork.messages.getByClientMessageId(
            message.sender_id,
            message.client_message_id,
        )
        missingMessage = await unitOfWork.messages.getByClientMessageId(
            UserId("another-sender"),
            message.client_message_id,
        )

    assert foundMessage == message
    assert missingMessage is None


@pytest.mark.asyncio
async def test_conversation_cursor_is_stable_for_same_timestamp(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种 Repository 都应使用消息 ID 决胜相同创建时间。"""
    createdAt = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    messages = (
        createFixedMessage(
            messageSequence=3,
            senderId="user-a",
            recipientId="user-b",
            createdAt=createdAt,
        ),
        createFixedMessage(
            messageSequence=1,
            senderId="user-b",
            recipientId="user-a",
            createdAt=createdAt,
        ),
        createFixedMessage(
            messageSequence=2,
            senderId="user-a",
            recipientId="user-b",
            createdAt=createdAt,
        ),
        createFixedMessage(
            messageSequence=4,
            senderId="user-a",
            recipientId="unrelated-user",
            createdAt=createdAt,
        ),
    )
    async with unitOfWorkBackend.factory() as unitOfWork:
        for message in messages:
            await unitOfWork.messages.add(message)
        await unitOfWork.commit()

    async with unitOfWorkBackend.factory() as unitOfWork:
        firstPage = await unitOfWork.messages.listByConversation(
            ConversationId(TEST_CONVERSATION_ID),
            cursor=None,
            limit=2,
        )
        secondPage = await unitOfWork.messages.listByConversation(
            ConversationId(TEST_CONVERSATION_ID),
            cursor=MessageCursor.fromMessage(firstPage[-1]),
            limit=2,
        )
        emptyPage = await unitOfWork.messages.listByConversation(
            ConversationId(TEST_CONVERSATION_ID),
            cursor=MessageCursor.fromMessage(secondPage[-1]),
            limit=2,
        )

    assert [message.message_id.value.int for message in firstPage] == [1, 2]
    assert [message.message_id.value.int for message in secondPage] == [3]
    assert emptyPage == ()

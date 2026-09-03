"""内存与 SQLAlchemy 消息工作单元的共同契约测试。"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.adapters import InMemoryMessageUnitOfWorkFactory
from src.adapters.database import (
    MessageRecord,
    SqlAlchemyMessageUnitOfWorkFactory,
    createSessionFactory,
    createSqliteEngine,
    toDomainMessage,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.application import MessageCursor, MessageUnitOfWorkFactory
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)
from src.domain import create_chat_message as createChatMessage


@dataclass(frozen=True, slots=True)
class UnitOfWorkBackend:
    """供共同契约读取已提交状态的测试后端。"""

    factory: MessageUnitOfWorkFactory
    loadMessages: Callable[[], tuple[ChatMessage, ...]]


@pytest.fixture(params=("memory", "sqlalchemy"))
def unitOfWorkBackend(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[UnitOfWorkBackend]:
    """为相同契约提供内存和 SQLite 两种后端。"""
    if request.param == "memory":
        factory = InMemoryMessageUnitOfWorkFactory()
        yield UnitOfWorkBackend(factory=factory, loadMessages=lambda: factory.messages)
        return

    databasePath = tmp_path / "contract.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createSqliteEngine(databasePath)
    sessionFactory = createSessionFactory(engine)
    try:
        yield UnitOfWorkBackend(
            factory=SqlAlchemyMessageUnitOfWorkFactory(sessionFactory),
            loadMessages=lambda: loadSqlAlchemyMessages(sessionFactory),
        )
    finally:
        engine.dispose()


def createMessage(content: str = "契约测试消息") -> ChatMessage:
    """创建共同契约使用的领域消息。"""
    return createChatMessage(
        client_message_id=ClientMessageId(uuid4()),
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
        sender_id=UserId(senderId),
        recipient_id=UserId(recipientId),
        content=MessageContent(f"message-{messageSequence}"),
        created_at=createdAt,
    )


def loadSqlAlchemyMessages(
    sessionFactory: sessionmaker[Session],
) -> tuple[ChatMessage, ...]:
    """从新 Session 加载所有已提交消息。"""
    with sessionFactory() as session:
        records = session.scalars(
            select(MessageRecord).order_by(MessageRecord.createdAt)
        ).all()
        return tuple(toDomainMessage(record) for record in records)


def test_committed_message_is_persisted(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现都必须持久化显式提交的消息。"""
    message = createMessage()

    with unitOfWorkBackend.factory() as unitOfWork:
        unitOfWork.messages.add(message)
        unitOfWork.commit()

    assert unitOfWorkBackend.loadMessages() == (message,)


def test_uncommitted_message_is_rolled_back(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现退出时都必须回滚未提交消息。"""
    with unitOfWorkBackend.factory() as unitOfWork:
        unitOfWork.messages.add(createMessage())

    assert unitOfWorkBackend.loadMessages() == ()


def test_exception_rolls_back_message(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种实现遇到异常时都必须回滚并传播异常。"""
    with pytest.raises(RuntimeError, match="模拟用例异常"):
        with unitOfWorkBackend.factory() as unitOfWork:
            unitOfWork.messages.add(createMessage())
            raise RuntimeError("模拟用例异常")

    assert unitOfWorkBackend.loadMessages() == ()


def test_get_by_sender_and_client_message_id(
    unitOfWorkBackend: UnitOfWorkBackend,
) -> None:
    """两种 Repository 都应按完整幂等键返回原消息。"""
    message = createMessage()
    with unitOfWorkBackend.factory() as unitOfWork:
        unitOfWork.messages.add(message)
        unitOfWork.commit()

    with unitOfWorkBackend.factory() as unitOfWork:
        foundMessage = unitOfWork.messages.getByClientMessageId(
            message.sender_id,
            message.client_message_id,
        )
        missingMessage = unitOfWork.messages.getByClientMessageId(
            UserId("another-sender"),
            message.client_message_id,
        )

    assert foundMessage == message
    assert missingMessage is None


def test_conversation_cursor_is_stable_for_same_timestamp(
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
    with unitOfWorkBackend.factory() as unitOfWork:
        for message in messages:
            unitOfWork.messages.add(message)
        unitOfWork.commit()

    with unitOfWorkBackend.factory() as unitOfWork:
        firstPage = unitOfWork.messages.listConversation(
            UserId("user-a"),
            UserId("user-b"),
            cursor=None,
            limit=2,
        )
        secondPage = unitOfWork.messages.listConversation(
            UserId("user-a"),
            UserId("user-b"),
            cursor=MessageCursor.fromMessage(firstPage[-1]),
            limit=2,
        )
        emptyPage = unitOfWork.messages.listConversation(
            UserId("user-a"),
            UserId("user-b"),
            cursor=MessageCursor.fromMessage(secondPage[-1]),
            limit=2,
        )

    assert [message.message_id.value.int for message in firstPage] == [1, 2]
    assert [message.message_id.value.int for message in secondPage] == [3]
    assert emptyPage == ()

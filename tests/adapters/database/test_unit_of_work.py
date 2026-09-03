"""SQLAlchemy 消息 Repository 与 Unit of Work 集成测试。"""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.database import (
    MessageRecord,
    SqlAlchemyMessageUnitOfWorkFactory,
    createSessionFactory,
    createSqliteEngine,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.application import MessageStorageError
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)
from src.domain import create_chat_message as createChatMessage


@pytest.fixture
def databaseEngine(tmp_path: Path) -> Iterator[Engine]:
    """创建具有消息表的临时 SQLite Engine。"""
    databasePath = tmp_path / "unit-of-work.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createSqliteEngine(databasePath)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sessionFactory(databaseEngine: Engine) -> sessionmaker[Session]:
    """创建测试使用的同步 Session 工厂。"""
    return createSessionFactory(databaseEngine)


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


def countMessages(sessionFactory: sessionmaker[Session]) -> int:
    """通过新 Session 统计已提交消息数。"""
    with sessionFactory() as session:
        return session.scalar(select(func.count()).select_from(MessageRecord)) or 0


def test_commit_failure_is_translated_and_session_remains_usable(
    sessionFactory: sessionmaker[Session],
) -> None:
    """约束导致的提交失败应转换异常、回滚并关闭失败 Session。"""
    firstMessage = createMessage(
        messageId=UUID("10000000-0000-0000-0000-000000000001"),
        clientMessageId=UUID("20000000-0000-0000-0000-000000000002"),
    )
    duplicateMessage = createMessage(
        messageId=UUID("30000000-0000-0000-0000-000000000003"),
        clientMessageId=UUID("20000000-0000-0000-0000-000000000002"),
    )
    unitOfWorkFactory = SqlAlchemyMessageUnitOfWorkFactory(sessionFactory)

    with unitOfWorkFactory() as unitOfWork:
        unitOfWork.messages.add(firstMessage)
        unitOfWork.commit()

    with pytest.raises(MessageStorageError, match="消息事务提交失败"):
        with unitOfWorkFactory() as unitOfWork:
            unitOfWork.messages.add(duplicateMessage)
            unitOfWork.commit()

    assert countMessages(sessionFactory) == 1

    # 提交失败的 Session 已关闭，后续工作单元仍能独立使用。
    thirdMessage = createMessage(
        messageId=UUID("40000000-0000-0000-0000-000000000004"),
        clientMessageId=UUID("50000000-0000-0000-0000-000000000005"),
    )
    with unitOfWorkFactory() as unitOfWork:
        unitOfWork.messages.add(thirdMessage)
        unitOfWork.commit()

    assert countMessages(sessionFactory) == 2

"""同步 Session 提交、回滚和关闭行为集成测试。"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.database import (
    MessageRecord,
    createSessionFactory,
    createSqliteEngine,
    toDomainMessage,
    toMessageRecord,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.domain import ClientMessageId, MessageContent, UserId, create_chat_message


@pytest.fixture
def databaseEngine(tmp_path: Path) -> Iterator[Engine]:
    """创建使用临时文件的 SQLite Engine。"""
    databasePath = tmp_path / "nested" / "messages.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createSqliteEngine(databasePath)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sessionFactory(databaseEngine: Engine) -> sessionmaker[Session]:
    """创建绑定测试 Engine 的同步 Session 工厂。"""
    return createSessionFactory(databaseEngine)


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
        sender_id=UserId(senderId),
        recipient_id=UserId("recipient-b"),
        content=MessageContent("事务测试消息"),
    )
    return toMessageRecord(message)


def test_engine_uses_configured_path_and_connection_closes(tmp_path: Path) -> None:
    """Engine 应使用 pathlib 路径，Connection 应可显式关闭。"""
    databasePath = tmp_path / "nested" / "configured.sqlite3"
    engine = createSqliteEngine(databasePath)
    try:
        assert Path(engine.url.database or "") == databasePath.resolve()
        assert databasePath.parent.is_dir()

        connection = engine.connect()
        assert not connection.closed
        connection.close()
        assert connection.closed
    finally:
        engine.dispose()


def test_commit_is_visible_to_a_new_session(
    sessionFactory: sessionmaker[Session],
) -> None:
    """提交后的记录应能被新 Session 查询。"""
    record = createRecord()
    messageId = record.messageId

    with sessionFactory() as session:
        session.add(record)
        session.flush()
        assert inspect(record).persistent
        session.commit()

    with sessionFactory() as session:
        statement = select(MessageRecord).where(MessageRecord.messageId == messageId)
        persistedRecord = session.scalars(statement).one()
        persistedMessage = toDomainMessage(persistedRecord)

    assert str(persistedMessage.message_id) == messageId
    assert persistedMessage.created_at.utcoffset() == timedelta(0)


def test_rollback_is_not_visible_to_a_new_session(
    sessionFactory: sessionmaker[Session],
) -> None:
    """刷新后回滚的记录不应被新 Session 查询。"""
    record = createRecord()

    with sessionFactory() as session:
        session.add(record)
        session.flush()
        session.rollback()

    with sessionFactory() as session:
        statement = select(MessageRecord).where(
            MessageRecord.messageId == record.messageId
        )
        assert session.scalars(statement).one_or_none() is None


def test_close_rolls_back_transaction_and_detaches_record(
    sessionFactory: sessionmaker[Session],
) -> None:
    """关闭 Session 应释放对象并回滚尚未提交的事务。"""
    record = createRecord()
    session = sessionFactory()
    session.add(record)
    session.flush()

    session.close()

    assert inspect(record).detached
    with sessionFactory() as verificationSession:
        statement = select(MessageRecord).where(
            MessageRecord.messageId == record.messageId
        )
        assert verificationSession.scalars(statement).one_or_none() is None


def test_sender_and_client_message_id_are_unique_together(
    sessionFactory: sessionmaker[Session],
) -> None:
    """同一发送者不能重复保存相同客户端消息标识。"""
    clientMessageId = uuid4()
    firstRecord = createRecord(clientMessageId=clientMessageId)
    duplicateRecord = createRecord(clientMessageId=clientMessageId)

    with sessionFactory() as session:
        session.add(firstRecord)
        session.commit()

    with sessionFactory() as session:
        session.add(duplicateRecord)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

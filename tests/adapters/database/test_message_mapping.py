"""消息 ORM 映射和领域转换测试。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import inspect

from src.adapters.database import (
    MessageRecord,
    createDatabaseSchema,
    createSqliteEngine,
    toDomainMessage,
    toMessageRecord,
)
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)


def createMessage() -> ChatMessage:
    """创建具有固定值的领域消息测试样本。"""
    return ChatMessage(
        message_id=MessageId(UUID("10000000-0000-0000-0000-000000000001")),
        client_message_id=ClientMessageId(UUID("20000000-0000-0000-0000-000000000002")),
        sender_id=UserId("sender-a"),
        recipient_id=UserId("recipient-b"),
        content=MessageContent("测试消息"),
        created_at=datetime(
            2026,
            9,
            3,
            12,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )


def test_message_table_has_explained_constraints_and_index(tmp_path) -> None:
    """消息表应包含身份、幂等和收件箱查询所需结构。"""
    engine = createSqliteEngine(tmp_path / "schema.sqlite3")
    try:
        createDatabaseSchema(engine)
        inspector = inspect(engine)

        columns = {
            column["name"]: column for column in inspector.get_columns("messages")
        }
        assert set(columns) == {
            "message_id",
            "client_message_id",
            "sender_id",
            "recipient_id",
            "content",
            "created_at",
        }
        assert inspector.get_pk_constraint("messages")["constrained_columns"] == [
            "message_id"
        ]

        uniqueConstraints = inspector.get_unique_constraints("messages")
        assert {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in uniqueConstraints
        } == {
            (
                "uq_messages_sender_client_message",
                ("sender_id", "client_message_id"),
            )
        }

        indexes = inspector.get_indexes("messages")
        assert {(index["name"], tuple(index["column_names"])) for index in indexes} == {
            (
                "ix_messages_recipient_created_message",
                ("recipient_id", "created_at", "message_id"),
            )
        }

        checkNames = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("messages")
        }
        assert checkNames == {
            "ck_messages_client_message_id_length",
            "ck_messages_content_length",
            "ck_messages_message_id_length",
            "ck_messages_recipient_id_not_blank",
            "ck_messages_sender_id_not_blank",
        }
    finally:
        engine.dispose()


def test_message_conversion_keeps_domain_separate_from_orm() -> None:
    """显式转换应保持领域值且不让领域对象依赖 ORM。"""
    message = createMessage()

    record = toMessageRecord(message)
    restoredMessage = toDomainMessage(record)

    assert isinstance(record, MessageRecord)
    assert restoredMessage == message
    assert restoredMessage.client_message_id == message.client_message_id
    assert restoredMessage.sender_id == message.sender_id
    assert restoredMessage.recipient_id == message.recipient_id
    assert restoredMessage.content == message.content
    assert restoredMessage.created_at == message.created_at

"""
同步 SQLAlchemy 插入、查询和回滚学习实验

使用方法：
    uv run python -m examples.sqlAlchemyExperiment
"""

import argparse
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from src.adapters.database.connection import (
    createDatabaseSchema,
    createSessionFactory,
    createSqliteEngine,
)
from src.adapters.database.messageMapper import toDomainMessage, toMessageRecord
from src.adapters.database.models import MessageRecord
from src.config import DATABASE_PATH
from src.domain import ClientMessageId, MessageContent, UserId, create_chat_message


def runExperiment(databasePath: Path) -> None:
    """运行提交后查询和回滚后不可见的独立实验。"""
    engine = createSqliteEngine(databasePath, echo=True)
    sessionFactory = createSessionFactory(engine)
    createDatabaseSchema(engine)

    committedMessage = create_chat_message(
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("experiment-sender"),
        recipient_id=UserId("experiment-recipient"),
        content=MessageContent("这条消息会被提交"),
    )
    rolledBackMessage = create_chat_message(
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("experiment-sender"),
        recipient_id=UserId("experiment-recipient"),
        content=MessageContent("这条消息会被回滚"),
    )

    try:
        with sessionFactory() as session:
            session.add(toMessageRecord(committedMessage))
            session.flush()
            session.commit()

        with sessionFactory() as session:
            statement = select(MessageRecord).where(
                MessageRecord.messageId == str(committedMessage.message_id)
            )
            committedRecord = session.scalars(statement).one()
            loadedMessage = toDomainMessage(committedRecord)
            print(f"提交后查询成功: {loadedMessage.message_id}")

        with sessionFactory() as session:
            session.add(toMessageRecord(rolledBackMessage))
            session.flush()
            session.rollback()

        with sessionFactory() as session:
            statement = select(MessageRecord).where(
                MessageRecord.messageId == str(rolledBackMessage.message_id)
            )
            if session.scalars(statement).one_or_none() is not None:
                raise RuntimeError("回滚消息不应被新 Session 查询到")
            print(f"回滚后查询不到消息: {rolledBackMessage.message_id}")
    finally:
        engine.dispose()


def main() -> None:
    """解析实验参数并执行。"""
    parser = argparse.ArgumentParser(description="同步 SQLAlchemy 消息持久化实验")
    parser.add_argument(
        "--database-path",
        dest="databasePath",
        type=Path,
        default=DATABASE_PATH,
        help="SQLite 数据库文件路径",
    )
    arguments = parser.parse_args()
    runExperiment(arguments.databasePath)


if __name__ == "__main__":
    main()

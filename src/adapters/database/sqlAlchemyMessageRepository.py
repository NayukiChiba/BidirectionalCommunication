"""基于同步 SQLAlchemy Session 的消息 Repository。"""

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.adapters.database.messageMapper import toDomainMessage, toMessageRecord
from src.adapters.database.models import MessageRecord
from src.application.exceptions import MessageStorageError
from src.application.models import MessageCursor
from src.domain import ChatMessage, ClientMessageId, UserId


class SqlAlchemyMessageRepository:
    """通过当前工作单元的 Session 暂存领域消息。"""

    def __init__(self, session: Session) -> None:
        """接收由工作单元管理生命周期的 Session。"""
        self._session = session

    def add(self, message: ChatMessage) -> None:
        """将领域消息转换为 ORM 记录并加入当前 Session。"""
        try:
            self._session.add(toMessageRecord(message))
        except SQLAlchemyError as error:
            raise MessageStorageError("消息加入数据库会话失败") from error

    def getByClientMessageId(
        self,
        senderId: UserId,
        clientMessageId: ClientMessageId,
    ) -> ChatMessage | None:
        """按数据库唯一幂等键查询原领域消息。"""
        statement = select(MessageRecord).where(
            MessageRecord.senderId == str(senderId),
            MessageRecord.clientMessageId == str(clientMessageId),
        )
        try:
            record = self._session.scalars(statement).one_or_none()
        except SQLAlchemyError as error:
            raise MessageStorageError("查询幂等消息失败") from error
        return toDomainMessage(record) if record is not None else None

    def listConversation(
        self,
        userId: UserId,
        peerId: UserId,
        *,
        cursor: MessageCursor | None,
        limit: int,
    ) -> tuple[ChatMessage, ...]:
        """使用稳定排他游标查询两个用户之间的消息。"""
        userValue = str(userId)
        peerValue = str(peerId)
        statement = select(MessageRecord).where(
            or_(
                and_(
                    MessageRecord.senderId == userValue,
                    MessageRecord.recipientId == peerValue,
                ),
                and_(
                    MessageRecord.senderId == peerValue,
                    MessageRecord.recipientId == userValue,
                ),
            )
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    MessageRecord.createdAt > cursor.created_at,
                    and_(
                        MessageRecord.createdAt == cursor.created_at,
                        MessageRecord.messageId > str(cursor.message_id),
                    ),
                )
            )
        statement = statement.order_by(
            MessageRecord.createdAt,
            MessageRecord.messageId,
        ).limit(limit)

        try:
            records = self._session.scalars(statement).all()
        except SQLAlchemyError as error:
            raise MessageStorageError("查询单聊历史失败") from error
        return tuple(toDomainMessage(record) for record in records)

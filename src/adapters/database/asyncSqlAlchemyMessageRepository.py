"""基于 AsyncSession 的消息 Repository。"""

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.messageMapper import toDomainMessage, toMessageRecord
from src.adapters.database.models import MessageRecord
from src.application.exceptions import MessageStorageError
from src.application.models import MessageCursor
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    MessageId,
    UserId,
)


class AsyncSqlAlchemyMessageRepository:
    """通过当前工作单元的 AsyncSession 访问消息。"""

    def __init__(self, session: AsyncSession) -> None:
        """接收由工作单元管理生命周期的 AsyncSession。"""
        self._session = session

    async def add(self, message: ChatMessage) -> None:
        """将领域消息转换为 ORM 记录并加入当前 AsyncSession。"""
        try:
            self._session.add(toMessageRecord(message))
        except SQLAlchemyError as error:
            raise MessageStorageError("消息加入数据库会话失败") from error

    async def getByClientMessageId(
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
            result = await self._session.scalars(statement)
            record = result.one_or_none()
        except SQLAlchemyError as error:
            raise MessageStorageError("查询幂等消息失败") from error
        return toDomainMessage(record) if record is not None else None

    async def getById(self, messageId: MessageId) -> ChatMessage | None:
        """按服务端消息 ID 查询领域消息。"""
        statement = select(MessageRecord).where(
            MessageRecord.messageId == str(messageId)
        )
        try:
            record = (await self._session.scalars(statement)).one_or_none()
        except SQLAlchemyError as error:
            raise MessageStorageError("按消息 ID 查询消息失败") from error
        return toDomainMessage(record) if record is not None else None

    async def listByConversation(
        self,
        conversationId: ConversationId,
        *,
        cursor: MessageCursor | None,
        limit: int,
    ) -> tuple[ChatMessage, ...]:
        """使用稳定排他游标查询一个会话中的消息。"""
        statement = select(MessageRecord).where(
            MessageRecord.conversationId == str(conversationId)
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
            result = await self._session.scalars(statement)
            records = result.all()
        except SQLAlchemyError as error:
            raise MessageStorageError("查询单聊历史失败") from error
        return tuple(toDomainMessage(record) for record in records)

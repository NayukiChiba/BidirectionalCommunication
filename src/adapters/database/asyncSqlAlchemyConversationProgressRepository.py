"""基于 AsyncSession 的会话成员累计位置 Repository。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.messageMapper import normalizeDatabaseDatetime
from src.adapters.database.models import ConversationMemberRecord
from src.application.exceptions import ConversationStorageError
from src.domain import (
    ConversationId,
    ConversationProgress,
    MessageId,
    MessagePosition,
    UserId,
)


class AsyncSqlAlchemyConversationProgressRepository:
    """使用条件 UPDATE 保证并发确认也只能向前推进。"""

    def __init__(self, session: AsyncSession) -> None:
        """接收由会话工作单元管理的 AsyncSession。"""
        self._session = session

    async def get(
        self,
        conversationId: ConversationId,
        memberId: UserId,
    ) -> ConversationProgress | None:
        """读取成员当前累计位置。"""
        statement = select(ConversationMemberRecord).where(
            ConversationMemberRecord.conversationId == str(conversationId),
            ConversationMemberRecord.userId == str(memberId),
        )
        try:
            record = (await self._session.scalars(statement)).one_or_none()
        except SQLAlchemyError as error:
            raise ConversationStorageError("查询会话成员进度失败") from error
        if record is None:
            return None
        return ConversationProgress(
            conversation_id=conversationId,
            member_id=memberId,
            delivered_position=self._toPosition(
                record.deliveredCreatedAt,
                record.deliveredMessageId,
            ),
            read_position=self._toPosition(
                record.readCreatedAt,
                record.readMessageId,
            ),
        )

    async def advanceDelivered(
        self,
        conversationId: ConversationId,
        memberId: UserId,
        position: MessagePosition,
    ) -> bool:
        """以数据库比较条件原子推进已送达游标。"""
        targetMessageId = str(position.message_id)
        statement = (
            update(ConversationMemberRecord)
            .where(
                ConversationMemberRecord.conversationId == str(conversationId),
                ConversationMemberRecord.userId == str(memberId),
                self._isBehind(
                    ConversationMemberRecord.deliveredCreatedAt,
                    ConversationMemberRecord.deliveredMessageId,
                    position,
                ),
            )
            .values(
                deliveredCreatedAt=position.created_at,
                deliveredMessageId=targetMessageId,
            )
        )
        return await self._executeAdvance(statement)

    async def advanceRead(
        self,
        conversationId: ConversationId,
        memberId: UserId,
        position: MessagePosition,
    ) -> bool:
        """在已送达范围内原子推进已读游标。"""
        targetMessageId = str(position.message_id)
        deliveredCoversTarget = or_(
            ConversationMemberRecord.deliveredCreatedAt > position.created_at,
            and_(
                ConversationMemberRecord.deliveredCreatedAt == position.created_at,
                ConversationMemberRecord.deliveredMessageId >= targetMessageId,
            ),
        )
        statement = (
            update(ConversationMemberRecord)
            .where(
                ConversationMemberRecord.conversationId == str(conversationId),
                ConversationMemberRecord.userId == str(memberId),
                deliveredCoversTarget,
                self._isBehind(
                    ConversationMemberRecord.readCreatedAt,
                    ConversationMemberRecord.readMessageId,
                    position,
                ),
            )
            .values(
                readCreatedAt=position.created_at,
                readMessageId=targetMessageId,
            )
        )
        return await self._executeAdvance(statement)

    async def _executeAdvance(self, statement: Any) -> bool:
        """执行条件更新并返回是否实际推进。"""
        try:
            result = await self._session.execute(statement)
        except SQLAlchemyError as error:
            raise ConversationStorageError("推进会话成员位置失败") from error
        return result.rowcount == 1

    @staticmethod
    def _isBehind(
        createdAtColumn: Any,
        messageIdColumn: Any,
        position: MessagePosition,
    ) -> Any:
        """构造“当前为空或严格落后于目标”的 SQL 条件。"""
        return or_(
            createdAtColumn.is_(None),
            createdAtColumn < position.created_at,
            and_(
                createdAtColumn == position.created_at,
                messageIdColumn < str(position.message_id),
            ),
        )

    @staticmethod
    def _toPosition(
        createdAt: datetime | None,
        messageId: str | None,
    ) -> MessagePosition | None:
        """把两个成对可空字段转换成领域位置。"""
        if createdAt is None or messageId is None:
            return None
        return MessagePosition(
            created_at=normalizeDatabaseDatetime(createdAt),
            message_id=MessageId(UUID(messageId)),
        )

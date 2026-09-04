"""基于 AsyncSession 的 Conversation 聚合 Repository。"""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.adapters.database.conversationMapper import (
    toConversationRecord,
    toDomainConversation,
)
from src.adapters.database.models import ConversationRecord
from src.application.exceptions import ConversationStorageError
from src.domain import Conversation, ConversationId, UserId


class AsyncSqlAlchemyConversationRepository:
    """通过当前工作单元的 AsyncSession 保存和读取完整会话聚合。"""

    def __init__(self, session: AsyncSession) -> None:
        """接收由工作单元管理生命周期的 AsyncSession。"""
        self._session = session

    async def add(self, conversation: Conversation) -> None:
        """把聚合根和两个成员加入同一数据库事务。"""
        try:
            self._session.add(toConversationRecord(conversation))
        except SQLAlchemyError as error:
            raise ConversationStorageError("会话加入数据库会话失败") from error

    async def getById(
        self,
        conversationId: ConversationId,
    ) -> Conversation | None:
        """按会话 ID 加载根记录和完整成员集合。"""
        statement = (
            select(ConversationRecord)
            .options(selectinload(ConversationRecord.members))
            .where(ConversationRecord.conversationId == str(conversationId))
        )
        return await self._getOne(statement)

    async def getByMembers(
        self,
        firstMemberId: UserId,
        secondMemberId: UserId,
    ) -> Conversation | None:
        """按规范化成员组合查询唯一一对一会话。"""
        pairKey = ":".join(sorted((str(firstMemberId), str(secondMemberId))))
        statement = (
            select(ConversationRecord)
            .options(selectinload(ConversationRecord.members))
            .where(ConversationRecord.memberPairKey == pairKey)
        )
        return await self._getOne(statement)

    async def _getOne(self, statement: object) -> Conversation | None:
        """执行唯一会话查询并统一转换存储异常。"""
        try:
            record = (await self._session.scalars(statement)).one_or_none()
        except SQLAlchemyError as error:
            raise ConversationStorageError("查询会话失败") from error
        return toDomainConversation(record) if record is not None else None

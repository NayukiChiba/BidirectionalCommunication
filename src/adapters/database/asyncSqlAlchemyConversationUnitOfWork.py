"""使用 AsyncSession 实现 Conversation 聚合工作单元。"""

from types import TracebackType

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.database.asyncSqlAlchemyConversationProgressRepository import (
    AsyncSqlAlchemyConversationProgressRepository,
)
from src.adapters.database.asyncSqlAlchemyConversationRepository import (
    AsyncSqlAlchemyConversationRepository,
)
from src.adapters.database.asyncSqlAlchemyMessageRepository import (
    AsyncSqlAlchemyMessageRepository,
)
from src.application.conversationPorts import (
    ConversationProgressRepository,
    ConversationRepository,
)
from src.application.exceptions import (
    ConversationStorageConflictError,
    ConversationStorageError,
)
from src.application.ports import MessageRepository


class AsyncSqlAlchemyConversationUnitOfWork:
    """原子保存会话根和成员，并管理 AsyncSession 生命周期。"""

    def __init__(self, sessionFactory: async_sessionmaker[AsyncSession]) -> None:
        """保存工厂，不跨 Task 共享 AsyncSession。"""
        self._sessionFactory = sessionFactory
        self._session: AsyncSession | None = None
        self.conversations: ConversationRepository
        self.progress: ConversationProgressRepository
        self.messages: MessageRepository

    async def __aenter__(self) -> "AsyncSqlAlchemyConversationUnitOfWork":
        """创建本次操作独占的 AsyncSession 和 Repository。"""
        if self._session is not None:
            raise RuntimeError("同一个会话工作单元不能重复进入")
        self._session = self._sessionFactory()
        self.conversations = AsyncSqlAlchemyConversationRepository(self._session)
        self.progress = AsyncSqlAlchemyConversationProgressRepository(self._session)
        self.messages = AsyncSqlAlchemyMessageRepository(self._session)
        return self

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """默认回滚未提交工作，并始终关闭 AsyncSession。"""
        session = self._session
        if session is None:
            return
        try:
            await self.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        """提交会话聚合，显式转换成员组合唯一冲突。"""
        session = self._requireSession()
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise ConversationStorageConflictError("会话成员组合已存在") from error
        except SQLAlchemyError as error:
            await session.rollback()
            raise ConversationStorageError("会话事务提交失败") from error

    async def rollback(self) -> None:
        """回滚当前事务中未提交的会话变更。"""
        await self._requireSession().rollback()

    def _requireSession(self) -> AsyncSession:
        """拒绝在工作单元范围外使用 Session。"""
        if self._session is None:
            raise RuntimeError("会话工作单元尚未进入事务范围")
        return self._session


class AsyncSqlAlchemyConversationUnitOfWorkFactory:
    """为每次会话操作创建独立异步工作单元。"""

    def __init__(self, sessionFactory: async_sessionmaker[AsyncSession]) -> None:
        """保存所有会话工作单元共享的 Session 配置工厂。"""
        self._sessionFactory = sessionFactory

    def __call__(self) -> AsyncSqlAlchemyConversationUnitOfWork:
        """创建尚未进入事务范围的新会话工作单元。"""
        return AsyncSqlAlchemyConversationUnitOfWork(self._sessionFactory)

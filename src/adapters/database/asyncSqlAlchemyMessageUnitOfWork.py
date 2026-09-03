"""使用 AsyncSession 实现消息工作单元。"""

from types import TracebackType

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.database.asyncSqlAlchemyMessageRepository import (
    AsyncSqlAlchemyMessageRepository,
)
from src.application.exceptions import (
    MessageStorageConflictError,
    MessageStorageError,
)
from src.application.ports import MessageRepository


class AsyncSqlAlchemyMessageUnitOfWork:
    """管理一次消息用例的 AsyncSession、事务和 Repository。"""

    def __init__(
        self,
        sessionFactory: async_sessionmaker[AsyncSession],
    ) -> None:
        """保存工厂，不提前创建或跨 Task 共享 AsyncSession。"""
        self._sessionFactory = sessionFactory
        self._session: AsyncSession | None = None
        self.messages: MessageRepository

    async def __aenter__(self) -> "AsyncSqlAlchemyMessageUnitOfWork":
        """创建本次工作单元独占的 AsyncSession 和 Repository。"""
        if self._session is not None:
            raise RuntimeError("同一个工作单元不能重复进入")

        self._session = self._sessionFactory()
        self.messages = AsyncSqlAlchemyMessageRepository(self._session)
        return self

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """默认回滚未提交工作，并始终异步关闭 Session。"""
        session = self._session
        if session is None:
            return

        try:
            await self.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        """提交当前 AsyncSession，失败时回滚并转换为应用异常。"""
        session = self._requireSession()
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise MessageStorageConflictError("消息幂等键或约束冲突") from error
        except SQLAlchemyError as error:
            await session.rollback()
            raise MessageStorageError("消息事务提交失败") from error

    async def rollback(self) -> None:
        """回滚当前 AsyncSession 中尚未提交的工作。"""
        await self._requireSession().rollback()

    def _requireSession(self) -> AsyncSession:
        """返回活动 AsyncSession，拒绝在事务范围外操作。"""
        if self._session is None:
            raise RuntimeError("工作单元尚未进入事务范围")
        return self._session


class AsyncSqlAlchemyMessageUnitOfWorkFactory:
    """为每次消息用例创建独立异步 SQLAlchemy 工作单元。"""

    def __init__(
        self,
        sessionFactory: async_sessionmaker[AsyncSession],
    ) -> None:
        """保存所有工作单元共享的 AsyncSession 配置工厂。"""
        self._sessionFactory = sessionFactory

    def __call__(self) -> AsyncSqlAlchemyMessageUnitOfWork:
        """创建尚未进入事务范围的新工作单元。"""
        return AsyncSqlAlchemyMessageUnitOfWork(self._sessionFactory)

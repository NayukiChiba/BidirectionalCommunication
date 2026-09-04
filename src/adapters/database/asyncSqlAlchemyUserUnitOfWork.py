"""使用 AsyncSession 实现用户认证工作单元。"""

from types import TracebackType

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.database.asyncSqlAlchemyUserRepository import (
    AsyncSqlAlchemyUserRepository,
)
from src.application.authPorts import UserRepository
from src.application.exceptions import UsernameAlreadyExists, UserStorageError


class AsyncSqlAlchemyUserUnitOfWork:
    """管理一次用户认证操作的 AsyncSession 和事务。"""

    def __init__(
        self,
        sessionFactory: async_sessionmaker[AsyncSession],
    ) -> None:
        """保存工厂，不提前创建或共享 AsyncSession。"""
        self._sessionFactory = sessionFactory
        self._session: AsyncSession | None = None
        self.users: UserRepository

    async def __aenter__(self) -> "AsyncSqlAlchemyUserUnitOfWork":
        """创建本次认证操作独占的 Session 和 Repository。"""
        if self._session is not None:
            raise RuntimeError("同一个用户工作单元不能重复进入")
        self._session = self._sessionFactory()
        self.users = AsyncSqlAlchemyUserRepository(self._session)
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
        """提交用户事务并转换唯一用户名冲突。"""
        session = self._requireSession()
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise UsernameAlreadyExists("用户名已存在") from error
        except SQLAlchemyError as error:
            await session.rollback()
            raise UserStorageError("用户事务提交失败") from error

    async def rollback(self) -> None:
        """回滚当前用户事务。"""
        await self._requireSession().rollback()

    def _requireSession(self) -> AsyncSession:
        """返回活动 Session，拒绝在事务范围外操作。"""
        if self._session is None:
            raise RuntimeError("用户工作单元尚未进入事务范围")
        return self._session


class AsyncSqlAlchemyUserUnitOfWorkFactory:
    """为每次认证操作创建独立用户工作单元。"""

    def __init__(
        self,
        sessionFactory: async_sessionmaker[AsyncSession],
    ) -> None:
        """保存所有用户工作单元共享的 Session 配置工厂。"""
        self._sessionFactory = sessionFactory

    def __call__(self) -> AsyncSqlAlchemyUserUnitOfWork:
        """创建尚未进入事务范围的新用户工作单元。"""
        return AsyncSqlAlchemyUserUnitOfWork(self._sessionFactory)

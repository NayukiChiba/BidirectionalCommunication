"""使用同步 SQLAlchemy Session 实现消息工作单元。"""

from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.database.sqlAlchemyMessageRepository import (
    SqlAlchemyMessageRepository,
)
from src.application.exceptions import MessageStorageError
from src.application.ports import MessageRepository


class SqlAlchemyMessageUnitOfWork:
    """管理一次消息用例的 Session、事务和 Repository。"""

    def __init__(self, sessionFactory: sessionmaker[Session]) -> None:
        """保存 Session 工厂，不提前创建或共享 Session。"""
        self._sessionFactory = sessionFactory
        self._session: Session | None = None
        self.messages: MessageRepository

    def __enter__(self) -> "SqlAlchemyMessageUnitOfWork":
        """创建本次工作单元独占的 Session 和 Repository。"""
        if self._session is not None:
            raise RuntimeError("同一个工作单元不能重复进入")

        self._session = self._sessionFactory()
        self.messages = SqlAlchemyMessageRepository(self._session)
        return self

    def __exit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """默认回滚未提交工作，并始终关闭 Session。"""
        session = self._session
        if session is None:
            return

        try:
            self.rollback()
        finally:
            session.close()
            self._session = None

    def commit(self) -> None:
        """提交当前 Session，失败时回滚并转换为应用异常。"""
        session = self._requireSession()
        try:
            session.commit()
        except SQLAlchemyError as error:
            session.rollback()
            raise MessageStorageError("消息事务提交失败") from error

    def rollback(self) -> None:
        """回滚当前 Session 中尚未提交的工作。"""
        self._requireSession().rollback()

    def _requireSession(self) -> Session:
        """返回活动 Session，拒绝在事务范围外操作。"""
        if self._session is None:
            raise RuntimeError("工作单元尚未进入事务范围")
        return self._session


class SqlAlchemyMessageUnitOfWorkFactory:
    """为每次消息用例创建独立 SQLAlchemy 工作单元。"""

    def __init__(self, sessionFactory: sessionmaker[Session]) -> None:
        """保存所有工作单元共享的 Session 配置工厂。"""
        self._sessionFactory = sessionFactory

    def __call__(self) -> SqlAlchemyMessageUnitOfWork:
        """创建尚未进入事务范围的新工作单元。"""
        return SqlAlchemyMessageUnitOfWork(self._sessionFactory)

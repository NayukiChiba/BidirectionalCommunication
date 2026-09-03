"""基于同步 SQLAlchemy Session 的消息 Repository。"""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.adapters.database.messageMapper import toMessageRecord
from src.application.exceptions import MessageStorageError
from src.domain import ChatMessage


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

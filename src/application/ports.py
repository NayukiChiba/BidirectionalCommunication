"""应用用例依赖的持久化、事务和通知端口。"""

from types import TracebackType
from typing import Protocol

from src.application.models import DeliveryOutcome
from src.domain import ChatMessage


class MessageRepository(Protocol):
    """发送消息用例需要的最小消息存储端口。"""

    def add(self, message: ChatMessage) -> None:
        """保存一条已经创建的聊天消息。"""
        ...


class MessageUnitOfWork(Protocol):
    """一次消息用例所需的最小原子事务端口。"""

    messages: MessageRepository

    def __enter__(self) -> "MessageUnitOfWork":
        """进入事务范围并提供消息 Repository。"""
        ...

    def __exit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出事务范围，默认回滚未提交工作并释放资源。"""
        ...

    def commit(self) -> None:
        """显式提交当前工作单元。"""
        ...

    def rollback(self) -> None:
        """回滚当前工作单元。"""
        ...


class MessageUnitOfWorkFactory(Protocol):
    """为每次应用用例创建独立工作单元。"""

    def __call__(self) -> MessageUnitOfWork:
        """创建尚未进入事务范围的工作单元。"""
        ...


class MessageNotifier(Protocol):
    """发送消息用例需要的最小实时通知端口。"""

    async def deliver(self, message: ChatMessage) -> DeliveryOutcome:
        """尝试将消息实时投递给接收者。"""
        ...

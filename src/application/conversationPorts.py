"""一对一会话用例依赖的存储和事务端口。"""

from types import TracebackType
from typing import Protocol

from src.domain import Conversation, ConversationId, UserId


class ConversationRepository(Protocol):
    """以 Conversation 聚合和成员查询语义组织的存储端口。"""

    async def add(self, conversation: Conversation) -> None:
        """保存完整的一对一会话聚合。"""
        ...

    async def getById(
        self,
        conversationId: ConversationId,
    ) -> Conversation | None:
        """按聚合身份查询会话。"""
        ...

    async def getByMembers(
        self,
        firstMemberId: UserId,
        secondMemberId: UserId,
    ) -> Conversation | None:
        """按与输入顺序无关的两名成员查询会话。"""
        ...


class ConversationUnitOfWork(Protocol):
    """一次会话聚合操作的原子事务边界。"""

    conversations: ConversationRepository

    async def __aenter__(self) -> "ConversationUnitOfWork":
        """进入事务并提供会话 Repository。"""
        ...

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """默认回滚并释放会话资源。"""
        ...

    async def commit(self) -> None:
        """显式提交当前会话事务。"""
        ...

    async def rollback(self) -> None:
        """回滚当前会话事务。"""
        ...


class ConversationUnitOfWorkFactory(Protocol):
    """为每次会话操作创建独立工作单元。"""

    def __call__(self) -> ConversationUnitOfWork:
        """创建尚未进入事务范围的会话工作单元。"""
        ...

"""供快速单元测试使用的内存消息工作单元。"""

from types import TracebackType

from src.adapters.inMemoryMessageRepository import InMemoryMessageRepository
from src.domain import ChatMessage, MessageId


class InMemoryMessageUnitOfWork:
    """通过暂存消息模拟显式提交和默认回滚。"""

    def __init__(self, committedMessages: dict[MessageId, ChatMessage]) -> None:
        """接收工厂持有的已提交消息存储。"""
        self._committedMessages = committedMessages
        self._workingMessages = committedMessages.copy()
        self.messages = InMemoryMessageRepository(self._workingMessages)
        self._committed = False
        self._active = False

    async def __aenter__(self) -> "InMemoryMessageUnitOfWork":
        """异步进入新的内存事务范围。"""
        if self._active:
            raise RuntimeError("同一个工作单元不能重复进入")
        self._active = True
        return self

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """未显式提交或发生异常时丢弃暂存消息。"""
        try:
            if exceptionType is not None or not self._committed:
                await self.rollback()
        finally:
            self._active = False

    async def commit(self) -> None:
        """把当前工作单元的暂存消息写入共享内存存储。"""
        self._requireActive()
        self._committedMessages.update(self._workingMessages)
        self._committed = True

    async def rollback(self) -> None:
        """丢弃当前工作单元尚未提交的消息。"""
        self._requireActive()
        self._workingMessages.clear()

    def _requireActive(self) -> None:
        """拒绝在事务范围外提交或回滚。"""
        if not self._active:
            raise RuntimeError("工作单元尚未进入事务范围")


class InMemoryMessageUnitOfWorkFactory:
    """创建共享已提交状态、隔离暂存状态的内存工作单元。"""

    def __init__(self) -> None:
        """创建空的已提交消息存储。"""
        self._committedMessages: dict[MessageId, ChatMessage] = {}

    def __call__(self) -> InMemoryMessageUnitOfWork:
        """为一次用例创建新的内存工作单元。"""
        return InMemoryMessageUnitOfWork(self._committedMessages)

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        """返回所有已提交消息的只读快照。"""
        return tuple(self._committedMessages.values())

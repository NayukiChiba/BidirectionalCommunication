"""单聊历史消息应用服务测试。"""

from datetime import datetime, timezone
from types import TracebackType
from uuid import UUID

import pytest

from src.application import (
    GetMessageHistoryService,
    InvalidMessageHistoryQuery,
    MessageCursor,
    MessageHistoryQuery,
)
from src.domain import (
    ChatMessage,
    ClientMessageId,
    Conversation,
    ConversationId,
    MessageContent,
    MessageId,
    UserId,
)

TEST_CONVERSATION_ID = UUID("90000000-0000-0000-0000-000000000009")


class StubMessageRepository:
    """返回预设历史并记录查询参数。"""

    def __init__(self, messages: tuple[ChatMessage, ...]) -> None:
        self._messages = messages
        self.requestedLimit: int | None = None
        self.requestedCursor: MessageCursor | None = None

    async def listByConversation(
        self,
        conversationId: ConversationId,
        *,
        cursor: MessageCursor | None,
        limit: int,
    ) -> tuple[ChatMessage, ...]:
        """按调用方要求的数量返回预设消息。"""
        self.requestedLimit = limit
        self.requestedCursor = cursor
        return self._messages[:limit]


class StubMessageUnitOfWork:
    """为历史服务提供只读 Repository。"""

    def __init__(self, repository: StubMessageRepository) -> None:
        self.messages = repository

    async def __aenter__(self) -> "StubMessageUnitOfWork":
        return self

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        """只读测试不会提交。"""

    async def rollback(self) -> None:
        """只读测试无需维护状态。"""


class StubMessageUnitOfWorkFactory:
    """记录历史服务创建工作单元的次数。"""

    def __init__(self, repository: StubMessageRepository) -> None:
        self._repository = repository
        self.createdCount = 0

    def __call__(self) -> StubMessageUnitOfWork:
        self.createdCount += 1
        return StubMessageUnitOfWork(self._repository)


class StubConversationRepository:
    """返回固定的两人会话。"""

    async def getById(self, conversationId: ConversationId) -> Conversation | None:
        if conversationId.value != TEST_CONVERSATION_ID:
            return None
        return Conversation(
            conversation_id=conversationId,
            members=frozenset((UserId("user-a"), UserId("user-b"))),
            created_at=datetime.now(timezone.utc),
        )


class StubConversationUnitOfWork:
    """提供只读会话 Repository。"""

    conversations = StubConversationRepository()

    async def __aenter__(self) -> "StubConversationUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class StubConversationUnitOfWorkFactory:
    """创建只读会话工作单元。"""

    def __call__(self) -> StubConversationUnitOfWork:
        return StubConversationUnitOfWork()


def createService(factory: StubMessageUnitOfWorkFactory) -> GetMessageHistoryService:
    """组装带成员授权的历史查询服务。"""
    return GetMessageHistoryService(factory, StubConversationUnitOfWorkFactory())


def createMessage(sequence: int) -> ChatMessage:
    """创建按序号区分的固定时间领域消息。"""
    return ChatMessage(
        message_id=MessageId(UUID(int=sequence)),
        client_message_id=ClientMessageId(UUID(int=sequence + 100)),
        conversation_id=ConversationId(TEST_CONVERSATION_ID),
        sender_id=UserId("user-a"),
        recipient_id=UserId("user-b"),
        content=MessageContent(f"message-{sequence}"),
        created_at=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_history_service_requests_one_extra_message_for_has_more() -> None:
    """服务应多取一条判断后续页并返回最后可见消息游标。"""
    messages = tuple(createMessage(sequence) for sequence in range(1, 4))
    repository = StubMessageRepository(messages)
    unitOfWorkFactory = StubMessageUnitOfWorkFactory(repository)
    service = createService(unitOfWorkFactory)

    page = await service.getPage(
        MessageHistoryQuery(
            user_id="user-a",
            conversation_id=TEST_CONVERSATION_ID,
            limit=2,
        )
    )

    assert page.messages == messages[:2]
    assert page.has_more is True
    assert page.next_cursor == MessageCursor.fromMessage(messages[1])
    assert repository.requestedLimit == 3
    assert unitOfWorkFactory.createdCount == 1


@pytest.mark.asyncio
async def test_history_service_returns_empty_page() -> None:
    """没有历史时应返回空消息和空下一游标。"""
    repository = StubMessageRepository(())
    service = createService(StubMessageUnitOfWorkFactory(repository))

    page = await service.getPage(
        MessageHistoryQuery(
            user_id="user-a",
            conversation_id=TEST_CONVERSATION_ID,
        )
    )

    assert page.messages == ()
    assert page.next_cursor is None
    assert page.has_more is False


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
@pytest.mark.asyncio
async def test_history_service_rejects_invalid_page_size(limit: object) -> None:
    """分页大小必须是 1 到 100 之间的整数。"""
    repository = StubMessageRepository(())
    unitOfWorkFactory = StubMessageUnitOfWorkFactory(repository)
    service = createService(unitOfWorkFactory)

    with pytest.raises(InvalidMessageHistoryQuery):
        await service.getPage(
            MessageHistoryQuery(
                user_id="user-a",
                conversation_id=TEST_CONVERSATION_ID,
                limit=limit,  # type: ignore[arg-type]
            )
        )

    assert unitOfWorkFactory.createdCount == 0


def test_history_cursor_requires_timezone() -> None:
    """无时区游标会破坏跨数据库排序，应在应用边界拒绝。"""
    with pytest.raises(InvalidMessageHistoryQuery):
        MessageCursor(
            created_at=datetime(2026, 9, 3, 12, 0),
            message_id=UUID(int=1),
        )

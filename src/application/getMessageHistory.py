"""查询单聊历史消息的应用用例。"""

from src.application.exceptions import InvalidMessageHistoryQuery
from src.application.models import (
    MAX_HISTORY_PAGE_SIZE,
    MessageCursor,
    MessageHistoryPage,
    MessageHistoryQuery,
)
from src.application.ports import MessageUnitOfWorkFactory
from src.domain import DomainError, UserId


class GetMessageHistoryService:
    """通过正向稳定游标查询两个用户之间的消息。"""

    def __init__(self, unitOfWorkFactory: MessageUnitOfWorkFactory) -> None:
        """接收为每次查询创建独立工作单元的工厂。"""
        self._unitOfWorkFactory = unitOfWorkFactory

    def getPage(self, query: MessageHistoryQuery) -> MessageHistoryPage:
        """返回一页按创建时间和消息 ID 正向排列的消息。"""
        userId, peerId = self._validateQuery(query)

        with self._unitOfWorkFactory() as unitOfWork:
            messages = unitOfWork.messages.listConversation(
                userId,
                peerId,
                cursor=query.cursor,
                limit=query.limit + 1,
            )

        hasMore = len(messages) > query.limit
        pageMessages = messages[: query.limit]
        nextCursor = (
            MessageCursor.fromMessage(pageMessages[-1]) if pageMessages else None
        )
        return MessageHistoryPage(
            messages=pageMessages,
            next_cursor=nextCursor,
            has_more=hasMore,
        )

    def _validateQuery(
        self,
        query: MessageHistoryQuery,
    ) -> tuple[UserId, UserId]:
        """验证分页范围和两个用户标识。"""
        if not isinstance(query.limit, int) or isinstance(query.limit, bool):
            raise InvalidMessageHistoryQuery("历史消息分页大小必须是整数")
        if query.limit < 1 or query.limit > MAX_HISTORY_PAGE_SIZE:
            raise InvalidMessageHistoryQuery(
                f"历史消息分页大小必须在 1 到 {MAX_HISTORY_PAGE_SIZE} 之间"
            )
        if query.cursor is not None and not isinstance(query.cursor, MessageCursor):
            raise InvalidMessageHistoryQuery("历史消息游标类型无效")

        try:
            return UserId(query.user_id), UserId(query.peer_id)
        except DomainError as error:
            raise InvalidMessageHistoryQuery("历史消息用户标识无效") from error

"""WebSocket 重连缺失消息同步用例。"""

from src.application.advanceConversationPosition import (
    AdvanceConversationPositionService,
)
from src.application.deliveryModels import (
    AdvancePositionCommand,
    PositionKind,
    SyncMessagesCommand,
    SyncMessagesResult,
)
from src.application.exceptions import InvalidConversationPosition
from src.application.getMessageHistory import GetMessageHistoryService
from src.application.models import (
    MAX_HISTORY_PAGE_SIZE,
    MessageCursor,
    MessageHistoryQuery,
)


class SyncMessagesService:
    """提交最后已知位置并返回其后的已提交消息。"""

    def __init__(
        self,
        positionService: AdvanceConversationPositionService,
        historyService: GetMessageHistoryService,
    ) -> None:
        """复用累计确认和稳定历史分页两个既有能力。"""
        self._positionService = positionService
        self._historyService = historyService

    async def sync(self, command: SyncMessagesCommand) -> SyncMessagesResult:
        """执行可安全重复的重连同步请求。"""
        if (
            not isinstance(command.limit, int)
            or isinstance(command.limit, bool)
            or command.limit < 1
            or command.limit > MAX_HISTORY_PAGE_SIZE
        ):
            raise InvalidConversationPosition(
                f"同步数量必须在 1 到 {MAX_HISTORY_PAGE_SIZE} 之间"
            )

        cursor = None
        if command.after_message_id is not None:
            positionResult = await self._positionService.advance(
                AdvancePositionCommand(
                    user_id=command.user_id,
                    conversation_id=command.conversation_id,
                    message_id=command.after_message_id,
                    kind=PositionKind.DELIVERED,
                )
            )
            cursor = MessageCursor(
                created_at=positionResult.requested_position.created_at,
                message_id=positionResult.requested_position.message_id.value,
            )

        page = await self._historyService.getPage(
            MessageHistoryQuery(
                user_id=command.user_id,
                conversation_id=command.conversation_id,
                cursor=cursor,
                limit=command.limit,
            )
        )
        return SyncMessagesResult(messages=page.messages, has_more=page.has_more)

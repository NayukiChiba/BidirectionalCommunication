"""推进会话成员累计送达或已读位置的应用用例。"""

from uuid import UUID

from src.application.conversationPorts import ConversationUnitOfWorkFactory
from src.application.deliveryModels import (
    AdvancePositionCommand,
    AdvancePositionResult,
    PositionKind,
)
from src.application.exceptions import (
    ConversationStorageError,
    ConversationUnavailable,
    InvalidConversationPosition,
)
from src.domain import (
    ConversationId,
    ConversationMemberRequired,
    DomainError,
    MessageId,
    MessagePosition,
    ReadPositionBeyondDelivery,
    UserId,
)


class AdvanceConversationPositionService:
    """校验会话消息后，以条件更新保证累计位置只前进。"""

    def __init__(
        self,
        unitOfWorkFactory: ConversationUnitOfWorkFactory,
    ) -> None:
        """接收同时提供会话、消息和进度的工作单元。"""
        self._unitOfWorkFactory = unitOfWorkFactory

    async def advance(
        self,
        command: AdvancePositionCommand,
    ) -> AdvancePositionResult:
        """推进当前位置；重复或较旧确认保持幂等。"""
        userId, conversationId, messageId = self._validateCommand(command)

        async with self._unitOfWorkFactory() as unitOfWork:
            conversation = await unitOfWork.conversations.getById(conversationId)
            if conversation is None:
                raise ConversationUnavailable("无法创建或访问该会话")
            try:
                conversation.requireMember(userId)
            except ConversationMemberRequired as error:
                raise ConversationUnavailable("无法创建或访问该会话") from error

            message = await unitOfWork.messages.getById(messageId)
            if message is None or message.conversation_id != conversationId:
                raise InvalidConversationPosition("确认位置不属于目标会话")
            position = MessagePosition(message.created_at, message.message_id)
            progress = await unitOfWork.progress.get(conversationId, userId)
            if progress is None:
                raise ConversationStorageError("会话成员缺少进度记录")

            if command.kind is PositionKind.DELIVERED:
                advanced = await unitOfWork.progress.advanceDelivered(
                    conversationId,
                    userId,
                    position,
                )
            else:
                try:
                    progress.requireReadable(position)
                except ReadPositionBeyondDelivery as error:
                    raise InvalidConversationPosition(str(error)) from error
                advanced = await unitOfWork.progress.advanceRead(
                    conversationId,
                    userId,
                    position,
                )

            refreshed = await unitOfWork.progress.get(conversationId, userId)
            if refreshed is None:
                raise ConversationStorageError("推进后无法读取会话成员进度")
            await unitOfWork.commit()

        effectivePosition = (
            refreshed.delivered_position
            if command.kind is PositionKind.DELIVERED
            else refreshed.read_position
        )
        return AdvancePositionResult(
            kind=command.kind,
            requested_position=position,
            effective_position=effectivePosition,
            advanced=advanced,
        )

    @staticmethod
    def _validateCommand(
        command: AdvancePositionCommand,
    ) -> tuple[UserId, ConversationId, MessageId]:
        """把应用输入转换成强类型领域标识。"""
        if not isinstance(command.kind, PositionKind):
            raise InvalidConversationPosition("确认位置类型无效")
        try:
            return (
                UserId(command.user_id),
                ConversationId(UUID(str(command.conversation_id))),
                MessageId(UUID(str(command.message_id))),
            )
        except (DomainError, ValueError) as error:
            raise InvalidConversationPosition("确认位置标识无效") from error

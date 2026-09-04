"""发送消息应用用例。"""

from uuid import UUID

from src.application.conversationPorts import ConversationUnitOfWorkFactory
from src.application.exceptions import (
    ConversationStorageError,
    MessageStorageConflictError,
    MessageStorageError,
)
from src.application.models import (
    DeliveryOutcome,
    SendMessageCommand,
    SendMessageResult,
    SendMessageStatus,
)
from src.application.ports import MessageNotifier, MessageUnitOfWorkFactory
from src.domain import (
    ChatMessage,
    ClientMessageId,
    ConversationId,
    ConversationMemberRequired,
    DomainError,
    MessageContent,
    UserId,
    create_chat_message,
)


class SendMessageService:
    """协调消息创建、保存和实时通知。"""

    def __init__(
        self,
        unitOfWorkFactory: MessageUnitOfWorkFactory,
        conversationUnitOfWorkFactory: ConversationUnitOfWorkFactory,
        notifier: MessageNotifier,
    ) -> None:
        """显式接收发送消息用例依赖的端口。"""
        self._unitOfWorkFactory = unitOfWorkFactory
        self._conversationUnitOfWorkFactory = conversationUnitOfWorkFactory
        self._notifier = notifier

    async def send(self, command: SendMessageCommand) -> SendMessageResult:
        """执行一次发送消息用例。"""
        try:
            clientMessageId = ClientMessageId(command.client_message_id)
            senderId = UserId(command.sender_id)
            conversationId = ConversationId(UUID(str(command.conversation_id)))
            async with self._conversationUnitOfWorkFactory() as conversationUnit:
                conversation = await conversationUnit.conversations.getById(
                    conversationId
                )
            if conversation is None:
                return SendMessageResult(
                    status=SendMessageStatus.CONVERSATION_UNAVAILABLE
                )
            conversation.requireMember(senderId)
            message = create_chat_message(
                client_message_id=clientMessageId,
                conversation_id=conversationId,
                sender_id=senderId,
                recipient_id=conversation.getOtherMember(senderId),
                content=MessageContent(command.content),
            )
        except ConversationMemberRequired:
            return SendMessageResult(status=SendMessageStatus.CONVERSATION_UNAVAILABLE)
        except ConversationStorageError:
            return SendMessageResult(status=SendMessageStatus.STORAGE_FAILED)
        except (DomainError, ValueError):
            return SendMessageResult(status=SendMessageStatus.INVALID_MESSAGE)

        try:
            async with self._unitOfWorkFactory() as unitOfWork:
                existingMessage = await unitOfWork.messages.getByClientMessageId(
                    senderId,
                    clientMessageId,
                )
                if existingMessage is None:
                    await unitOfWork.messages.add(message)
                    await unitOfWork.commit()
                elif existingMessage.conversation_id != conversationId:
                    return SendMessageResult(status=SendMessageStatus.INVALID_MESSAGE)
                else:
                    message = existingMessage
        except MessageStorageConflictError:
            try:
                recoveredMessage = await self._getExistingMessage(
                    senderId,
                    clientMessageId,
                )
            except MessageStorageError:
                recoveredMessage = None
            if recoveredMessage is None:
                return SendMessageResult(
                    status=SendMessageStatus.STORAGE_FAILED,
                    message=message,
                )
            if recoveredMessage.conversation_id != conversationId:
                return SendMessageResult(status=SendMessageStatus.INVALID_MESSAGE)
            message = recoveredMessage
        except MessageStorageError:
            return SendMessageResult(
                status=SendMessageStatus.STORAGE_FAILED,
                message=message,
            )

        delivery_outcome = await self._notifier.deliver(message)
        status_by_outcome = {
            DeliveryOutcome.DELIVERED: SendMessageStatus.DELIVERED,
            DeliveryOutcome.RECIPIENT_OFFLINE: (SendMessageStatus.RECIPIENT_OFFLINE),
            DeliveryOutcome.FAILED: SendMessageStatus.DELIVERY_FAILED,
        }
        return SendMessageResult(
            status=status_by_outcome[delivery_outcome],
            message=message,
        )

    async def _getExistingMessage(
        self,
        senderId: UserId,
        clientMessageId: ClientMessageId,
    ) -> ChatMessage | None:
        """在并发唯一约束冲突后通过新工作单元读取原消息。"""
        async with self._unitOfWorkFactory() as unitOfWork:
            return await unitOfWork.messages.getByClientMessageId(
                senderId,
                clientMessageId,
            )

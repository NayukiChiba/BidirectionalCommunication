"""发送消息应用用例。"""

from src.application.exceptions import (
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
        notifier: MessageNotifier,
    ) -> None:
        """显式接收发送消息用例依赖的端口。"""
        self._unitOfWorkFactory = unitOfWorkFactory
        self._notifier = notifier

    async def send(self, command: SendMessageCommand) -> SendMessageResult:
        """执行一次发送消息用例。"""
        try:
            clientMessageId = ClientMessageId(command.client_message_id)
            senderId = UserId(command.sender_id)
            message = create_chat_message(
                client_message_id=clientMessageId,
                sender_id=senderId,
                recipient_id=UserId(command.recipient_id),
                content=MessageContent(command.content),
            )
        except DomainError:
            return SendMessageResult(status=SendMessageStatus.INVALID_MESSAGE)

        try:
            with self._unitOfWorkFactory() as unitOfWork:
                existingMessage = unitOfWork.messages.getByClientMessageId(
                    senderId,
                    clientMessageId,
                )
                if existingMessage is None:
                    unitOfWork.messages.add(message)
                    unitOfWork.commit()
                else:
                    message = existingMessage
        except MessageStorageConflictError:
            try:
                recoveredMessage = self._getExistingMessage(senderId, clientMessageId)
            except MessageStorageError:
                recoveredMessage = None
            if recoveredMessage is None:
                return SendMessageResult(
                    status=SendMessageStatus.STORAGE_FAILED,
                    message=message,
                )
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

    def _getExistingMessage(
        self,
        senderId: UserId,
        clientMessageId: ClientMessageId,
    ) -> ChatMessage | None:
        """在并发唯一约束冲突后通过新工作单元读取原消息。"""
        with self._unitOfWorkFactory() as unitOfWork:
            return unitOfWork.messages.getByClientMessageId(
                senderId,
                clientMessageId,
            )

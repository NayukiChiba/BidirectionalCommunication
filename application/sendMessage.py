"""发送消息应用用例。"""

from application.exceptions import MessageStorageError
from application.models import (
    DeliveryOutcome,
    SendMessageCommand,
    SendMessageResult,
    SendMessageStatus,
)
from application.ports import MessageNotifier, MessageRepository
from domain import (
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
        repository: MessageRepository,
        notifier: MessageNotifier,
    ) -> None:
        """显式接收发送消息用例依赖的端口。"""
        self._repository = repository
        self._notifier = notifier

    async def send(self, command: SendMessageCommand) -> SendMessageResult:
        """执行一次发送消息用例。"""
        try:
            message = create_chat_message(
                client_message_id=ClientMessageId(command.client_message_id),
                sender_id=UserId(command.sender_id),
                recipient_id=UserId(command.recipient_id),
                content=MessageContent(command.content),
            )
        except DomainError:
            return SendMessageResult(status=SendMessageStatus.INVALID_MESSAGE)

        try:
            self._repository.add(message)
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

"""实时通知端口的 WebSocket 适配器。"""

from typing import Protocol

from src.adapters.webSocketConnectionManager import ConnectionSendOutcome
from src.application import DeliveryOutcome
from src.domain import ChatMessage


class JsonConnectionSender(Protocol):
    """WebSocket 通知适配器需要的连接发送能力。"""

    async def deliver_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> ConnectionSendOutcome:
        """尝试向用户当前连接发送 JSON 数据。"""
        ...


class WebSocketMessageNotifier:
    """将领域消息转换为协议事件并投递到当前 WebSocket 连接。"""

    def __init__(self, connection_sender: JsonConnectionSender) -> None:
        """接收连接发送能力。"""
        self._connection_sender = connection_sender

    async def deliver(self, message: ChatMessage) -> DeliveryOutcome:
        """尝试实时投递消息，并返回明确结果。"""
        event_data: dict[str, object] = {
            "type": "message",
            "server_message_id": str(message.message_id),
            "client_message_id": str(message.client_message_id),
            "conversation_id": str(message.conversation_id),
            "sender_id": str(message.sender_id),
            "recipient_id": str(message.recipient_id),
            "content": str(message.content),
            "sent_at": message.created_at.isoformat().replace("+00:00", "Z"),
        }
        connection_outcome = await self._connection_sender.deliver_to_user(
            user_id=message.recipient_id.value,
            data=event_data,
        )
        outcome_by_connection_result = {
            ConnectionSendOutcome.DELIVERED: DeliveryOutcome.PUSHED,
            ConnectionSendOutcome.RECIPIENT_OFFLINE: (
                DeliveryOutcome.RECIPIENT_OFFLINE
            ),
            ConnectionSendOutcome.FAILED: DeliveryOutcome.FAILED,
        }
        return outcome_by_connection_result[connection_outcome]

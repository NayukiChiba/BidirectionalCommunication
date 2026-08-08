"""WebSocket 消息通知适配器测试。"""

from uuid import uuid4

import pytest

from adapters import ConnectionSendOutcome, WebSocketMessageNotifier
from application import DeliveryOutcome
from domain import ClientMessageId, MessageContent, UserId, create_chat_message


class FakeConnectionSender:
    """记录 JSON 发送并返回预设连接结果。"""

    def __init__(self, outcome: ConnectionSendOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def deliver_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> ConnectionSendOutcome:
        """记录一次发送调用。"""
        self.calls.append((user_id, data))
        return self.outcome


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connection_outcome", "expected_outcome"),
    [
        pytest.param(
            ConnectionSendOutcome.DELIVERED,
            DeliveryOutcome.DELIVERED,
            id="delivered",
        ),
        pytest.param(
            ConnectionSendOutcome.RECIPIENT_OFFLINE,
            DeliveryOutcome.RECIPIENT_OFFLINE,
            id="recipient-offline",
        ),
        pytest.param(
            ConnectionSendOutcome.FAILED,
            DeliveryOutcome.FAILED,
            id="failed",
        ),
    ],
)
async def test_notifier_maps_connection_outcome(
    connection_outcome: ConnectionSendOutcome,
    expected_outcome: DeliveryOutcome,
) -> None:
    """通知适配器应保留实际连接发送结果的语义。"""
    connection_sender = FakeConnectionSender(connection_outcome)
    notifier = WebSocketMessageNotifier(connection_sender)
    message = create_chat_message(
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("user-a"),
        recipient_id=UserId("user-b"),
        content=MessageContent("Hello"),
    )

    outcome = await notifier.deliver(message)

    assert outcome is expected_outcome
    assert len(connection_sender.calls) == 1
    recipient_id, event_data = connection_sender.calls[0]
    assert recipient_id == "user-b"
    assert event_data == {
        "type": "message",
        "server_message_id": str(message.message_id),
        "client_message_id": str(message.client_message_id),
        "sender_id": "user-a",
        "recipient_id": "user-b",
        "content": "Hello",
        "sent_at": message.created_at.isoformat().replace("+00:00", "Z"),
    }

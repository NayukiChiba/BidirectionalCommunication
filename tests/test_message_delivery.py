"""
WebSocket 消息投递测试

功能：
1. 验证发送方发送消息
2. 验证接收方收到消息事件
3. 验证发送方收到确认事件
"""

from uuid import UUID

from fastapi.testclient import TestClient

from main import app

test_client = TestClient(app)


def test_deliver_message_and_acknowledge_sender() -> None:
    """测试接收方收到消息且发送方收到确认"""
    client_message_id = "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"

    with test_client.websocket_connect("/ws?user_id=user-b") as recipient_websocket:
        with test_client.websocket_connect("/ws?user_id=user-a") as sender_websocket:
            sender_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-b",
                    "content": "Hello World",
                    "client_message_id": client_message_id,
                }
            )
            message_event = recipient_websocket.receive_json()
            ack_event = sender_websocket.receive_json()

    assert message_event["type"] == "message"
    assert message_event["client_message_id"] == client_message_id
    assert message_event["content"] == "Hello World"
    assert message_event["recipient_id"] == "user-b"
    assert message_event["sender_id"] == "user-a"
    UUID(message_event["server_message_id"])

    assert ack_event["type"] == "ack"
    assert ack_event["client_message_id"] == client_message_id
    assert ack_event["server_message_id"] == message_event["server_message_id"]

"""
WebSocket 消息投递测试

功能：
1. 验证发送方发送消息
2. 验证接收方收到消息事件
3. 验证发送方收到确认事件
"""

from uuid import UUID

from fastapi.testclient import TestClient

from main import app, manager

test_client = TestClient(app)


def test_bidirectional_message_send_and_receive() -> None:
    """
    测试双向多消息
    """
    client_message_id = "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"
    user_b_client_message_id = "c2a54715-f62f-4aa2-a2b4-b8b7a316f2b5"

    with test_client.websocket_connect("/ws?user_id=user-b") as user_b_websocket:
        with test_client.websocket_connect("/ws?user_id=user-a") as user_a_websocket:
            message_a_events = []
            ack_a_events = []
            message_b_events = []
            ack_b_events = []
            # user_a 向 user_b 发送多条消息
            user_a_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-b",
                    "content": "Hello World",
                    "client_message_id": client_message_id,
                }
            )
            message_a_events.append(user_b_websocket.receive_json())
            ack_a_events.append(user_a_websocket.receive_json())

            user_a_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-b",
                    "content": "Hello World",
                    "client_message_id": client_message_id,
                }
            )
            message_a_events.append(user_b_websocket.receive_json())
            ack_a_events.append(user_a_websocket.receive_json())
            user_a_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-b",
                    "content": "Hello World",
                    "client_message_id": client_message_id,
                }
            )
            message_a_events.append(user_b_websocket.receive_json())
            ack_a_events.append(user_a_websocket.receive_json())
            # user_b 向 user_a 发送消息

            user_b_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-a",
                    "content": "Hello World",
                    "client_message_id": user_b_client_message_id,
                }
            )
            message_b_events.append(user_a_websocket.receive_json())
            ack_b_events.append(user_b_websocket.receive_json())

    for message_event, ack_event in zip(message_a_events, ack_a_events):
        assert message_event["type"] == "message"
        assert message_event["client_message_id"] == client_message_id
        assert message_event["content"] == "Hello World"
        assert message_event["recipient_id"] == "user-b"
        assert message_event["sender_id"] == "user-a"

        assert ack_event["type"] == "ack"
        assert ack_event["client_message_id"] == client_message_id
        assert ack_event["server_message_id"] == message_event["server_message_id"]
        UUID(message_event["server_message_id"])

    for message_event, ack_event in zip(message_b_events, ack_b_events):
        assert message_event["type"] == "message"
        assert message_event["client_message_id"] == user_b_client_message_id
        assert message_event["content"] == "Hello World"
        assert message_event["recipient_id"] == "user-a"
        assert message_event["sender_id"] == "user-b"

        assert ack_event["type"] == "ack"
        assert ack_event["client_message_id"] == user_b_client_message_id
        assert ack_event["server_message_id"] == message_event["server_message_id"]
        UUID(message_event["server_message_id"])


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


def test_send_message_to_offline_recipient() -> None:
    """测试向离线用户发送时发送方收到稳定错误"""
    client_message_id = "dd57b26c-5233-45d1-bf24-5bdc2f0fc68f"

    with test_client.websocket_connect("/ws?user_id=user-a") as sender_websocket:
        sender_websocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "offline-user",
                "content": "Hello",
                "client_message_id": client_message_id,
            }
        )
        error_event = sender_websocket.receive_json()

    assert error_event["type"] == "error"
    assert error_event["code"] == "recipient_offline"
    assert error_event["client_message_id"] == client_message_id


def test_allow_self_message() -> None:
    """测试明确允许用户向自己发送消息"""
    client_message_id = "819145f5-5ddb-4ae1-a382-f81fb81e6f08"

    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "user-a",
                "content": "写给自己",
                "client_message_id": client_message_id,
            }
        )
        message_event = websocket.receive_json()
        ack_event = websocket.receive_json()

    assert message_event["type"] == "message"
    assert message_event["sender_id"] == "user-a"
    assert message_event["recipient_id"] == "user-a"
    assert message_event["client_message_id"] == client_message_id
    assert ack_event["type"] == "ack"
    assert ack_event["server_message_id"] == message_event["server_message_id"]


def test_disconnect_cleans_endpoint_connection() -> None:
    """测试 WebSocket 退出后清理端点绑定的连接"""
    with test_client.websocket_connect("/ws?user_id=user-a"):
        assert manager.is_online("user-a") is True

    assert manager.is_online("user-a") is False

"""WebSocket 消息格式校验测试。"""

from fastapi.testclient import TestClient

from main import app

test_client = TestClient(app)


def test_websocket_invalid_json() -> None:
    """测试非法 JSON"""
    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_text('{"type":')
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["code"] == "invalid_json"


def test_websocket_blank_content() -> None:
    """测试空白消息内容"""
    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "user-b",
                "content": "    ",
                "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
            }
        )
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["code"] == "invalid_message"


def test_websocket_unknown_message_type() -> None:
    """测试未知消息类型"""
    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_json(
            {
                "type": "unknown",
                "recipient_id": "user-b",
                "content": "    ",
                "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
            }
        )
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["code"] == "invalid_message"

"""
FastAPI 接口测试
1. 健康测试
2. 测试 WebSocket 单条消息
3. 测试 WebSocket 连续消息
4. 测试 WebSocket 正常断开
"""

from uuid import UUID

from fastapi.testclient import TestClient

from main import app

test_client = TestClient(app)


def test_get_health() -> None:
    """
    测试健康检查端口
    """
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_websocket_valid_message() -> None:
    """
    测试合法的 WebSocket JSON 消息
    """
    client_message_id = "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"

    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "user-b",
                "content": "Hello World",
                "client_message_id": client_message_id,
            }
        )
        response = websocket.receive_json()

    assert response["type"] == "message"
    assert response["client_message_id"] == client_message_id
    assert response["content"] == "Hello World"
    assert response["recipient_id"] == "user-b"
    assert response["sender_id"] == "user-a"

    UUID(response["server_message_id"])

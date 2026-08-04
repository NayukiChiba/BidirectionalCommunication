"""WebSocket 消息格式校验测试。"""

from fastapi.testclient import TestClient

from main import app

test_client = TestClient(app)


# TODO(Issue 08 - 协议错误补全): 在已有非法 JSON、空白内容、错误 type 和发送者
# 防伪造测试基础上，补充缺少字段、超长字段和其他多余字段，并校验稳定错误结构及
# 可获得时的 client_message_id。发送者伪造用例还应确认接收方未收到消息。


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


def test_websocket_rejects_forged_sender_id() -> None:
    """测试客户端不能通过载荷伪造发送者 ID"""
    with test_client.websocket_connect("/ws?user_id=user-a") as websocket:
        websocket.send_json(
            {
                "type": "send_message",
                "sender_id": "user-c",
                "recipient_id": "user-b",
                "content": "伪造发送者",
                "client_message_id": "ff3596a2-cf49-45b5-9502-f68b11a0f04b",
            }
        )
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["code"] == "invalid_message"

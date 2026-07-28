"""
FastAPI 接口测试
1. 健康测试
2. 测试 WebSocket 单条消息
3. 测试 WebSocket 连续消息
4. 测试 WebSocket 正常断开
"""

from fastapi.testclient import TestClient

from main import app

testClient = TestClient(app)


def test_get_health() -> None:
    """
    测试健康检查端口
    """
    response = testClient.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_websocket_single_message() -> None:
    """
    测试单条 WebSocket 消息回显
    """
    sent_message = "Hello World"
    expected_message = f"我收到了内容, 内容是{sent_message}"

    with testClient.websocket_connect("/ws") as websocket:
        websocket.send_text(sent_message)
        response = websocket.receive_text()

    assert response == expected_message


def test_websocket_multiple_messages() -> None:
    """
    测试同一个 WebSocket 连接连续发消息
    """
    sent_messages = [
        "first message",
        "second message",
        "third message",
        "fourth message",
        "fifth message",
    ]

    with testClient.websocket_connect("/ws") as websocket:
        for sent_message in sent_messages:
            websocket.send_text(sent_message)
            response = websocket.receive_text()

            expected_message = f"我收到了内容, 内容是{sent_message}"

            assert response == expected_message


def test_websocketDisconnectNormally() -> None:
    """测试客户端主动断开连接"""
    with testClient.websocket_connect("/ws") as websocket:
        websocket.send_text("断开前的消息")
        receivedMessage = websocket.receive_text()

        assert receivedMessage == "我收到了内容, 内容是断开前的消息"

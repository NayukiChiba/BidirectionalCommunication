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


# TODO(Issue 08 - 双向多消息): 同时连接两个不同用户，验证 A -> B、B -> A、
# A -> B 多次投递；逐条校验 message 与 ack 的 client_message_id、
# server_message_id 对应，确保消息内容和发送者身份正确。

# TODO(Issue 08 - 重复登录接口验收): 用同一 user_id 依次建立两个 WebSocket；
# 断言旧连接以 4001 和固定原因关闭，新连接仍能收发消息，旧连接退出不影响新连接。

# TODO(Issue 08 - 任意顺序断开): 参数化验证 A 先断开、B 先断开以及重复登录后的
# 新旧连接交错退出；全部上下文结束后断言连接表为空，不使用固定时长 sleep。

# TODO(Issue 08 - 测试隔离): 将 TestClient 生命周期和连接表清理放入 fixture，
# 保证每个验收场景独立运行，测试结果不依赖执行顺序。


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

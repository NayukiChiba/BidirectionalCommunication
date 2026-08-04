"""
WebSocket 连接生命周期验收测试
"""

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from main import app, manager

test_client = TestClient(app)


def test_duplicate_login_replaces_old_connection() -> None:
    """
    测试重复登录会关闭旧连接, 而且不影响新连接
    """
    client_message_id = "819145f5-5ddb-4ae1-a382-f81fb81e6f08"

    with test_client.websocket_connect("/ws?user_id=user-a") as old_websocket:
        with test_client.websocket_connect("/ws?user_id=user-a") as new_websocket:
            with pytest.raises(WebSocketDisconnect) as exception_info:
                old_websocket.receive_text()

                assert exception_info.value.code == 4001
                assert exception_info.value.reason == "该账号已在其他连接登录"

            # 关闭旧连接, 新连接应该还是在线的
            old_websocket.close()
            assert manager.is_online("user-a") is True

            new_websocket.send_json(
                {
                    "type": "send_message",
                    "recipient_id": "user-a",
                    "content": "新连接仍然可用",
                    "client_message_id": client_message_id,
                }
            )

            message_event = new_websocket.receive_json()
            ack_event = new_websocket.receive_json()

            assert message_event["type"] == "message"
            assert message_event["content"] == "新连接仍然可用"
            assert message_event["client_message_id"] == client_message_id
            assert ack_event["type"] == "ack"
            assert ack_event["server_message_id"] == message_event["server_message_id"]

    assert manager.is_online("user-a") is False


# TODO(Issue 08 - 测试隔离): 将 TestClient 生命周期和连接表清理放入 fixture，
# 保证每个验收场景独立运行，测试结果不依赖执行顺序。


@pytest.mark.parametrize(
    ("first_user_id", "second_user_id"),
    [
        pytest.param("user-a", "user-b", id="user-a-first"),
        pytest.param("user-b", "user-a", id="user-b-first"),
    ],
)
def test_disconnect_users_in_any_order(
    first_user_id: str,
    second_user_id: str,
) -> None:
    """测试用户 A、B 按任意顺序断开后清空连接表。"""
    with test_client.websocket_connect("/ws?user_id=user-a") as user_a_websocket:
        with test_client.websocket_connect("/ws?user_id=user-b") as user_b_websocket:
            assert manager.is_online("user-a") is True
            assert manager.is_online("user-b") is True

            websockets = {
                "user-a": user_a_websocket,
                "user-b": user_b_websocket,
            }
            websockets[first_user_id].close()
            websockets[second_user_id].close()

    assert manager._connections == {}


@pytest.mark.parametrize(
    "old_connection_first",
    [
        pytest.param(True, id="old-connection-first"),
        pytest.param(False, id="new-connection-first"),
    ],
)
def test_disconnect_replaced_connections_in_any_order(
    old_connection_first: bool,
) -> None:
    """测试重复登录的新旧连接按任意顺序退出后清空连接表。"""
    with test_client.websocket_connect("/ws?user_id=user-a") as old_websocket:
        with test_client.websocket_connect("/ws?user_id=user-a") as new_websocket:
            if old_connection_first:
                first_websocket = old_websocket
                second_websocket = new_websocket
            else:
                first_websocket = new_websocket
                second_websocket = old_websocket

            first_websocket.close()
            second_websocket.close()

    assert manager._connections == {}

"""
WebSocket 连接生命周期验收测试
"""

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient


def test_duplicate_login_replaces_old_connection(
    testClient: TestClient,
    application: FastAPI,
) -> None:
    """
    测试重复登录会关闭旧连接, 而且不影响新连接
    """
    client_message_id = "819145f5-5ddb-4ae1-a382-f81fb81e6f08"

    connectionManager = application.state.connection_manager
    with testClient.websocket_connect("/ws?user_id=user-a") as old_websocket:
        with testClient.websocket_connect("/ws?user_id=user-a") as new_websocket:
            with pytest.raises(WebSocketDisconnect) as exception_info:
                old_websocket.receive_text()

                assert exception_info.value.code == 4001
                assert exception_info.value.reason == "该账号已在其他连接登录"

            # 关闭旧连接, 新连接应该还是在线的
            old_websocket.close()
            assert connectionManager.is_online("user-a") is True

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

    assert connectionManager.is_online("user-a") is False


@pytest.mark.parametrize(
    ("first_user_id", "second_user_id"),
    [
        pytest.param("user-a", "user-b", id="user-a-first"),
        pytest.param("user-b", "user-a", id="user-b-first"),
    ],
)
def test_disconnect_users_in_any_order(
    testClient: TestClient,
    application: FastAPI,
    first_user_id: str,
    second_user_id: str,
) -> None:
    """测试用户 A、B 按任意顺序断开后清空连接表。"""
    connectionManager = application.state.connection_manager
    with testClient.websocket_connect("/ws?user_id=user-a") as user_a_websocket:
        with testClient.websocket_connect("/ws?user_id=user-b") as user_b_websocket:
            assert connectionManager.is_online("user-a") is True
            assert connectionManager.is_online("user-b") is True

            websockets = {
                "user-a": user_a_websocket,
                "user-b": user_b_websocket,
            }
            websockets[first_user_id].close()
            websockets[second_user_id].close()

    assert connectionManager._connections == {}


@pytest.mark.parametrize(
    "old_connection_first",
    [
        pytest.param(True, id="old-connection-first"),
        pytest.param(False, id="new-connection-first"),
    ],
)
def test_disconnect_replaced_connections_in_any_order(
    testClient: TestClient,
    application: FastAPI,
    old_connection_first: bool,
) -> None:
    """测试重复登录的新旧连接按任意顺序退出后清空连接表。"""
    connectionManager = application.state.connection_manager
    with testClient.websocket_connect("/ws?user_id=user-a") as old_websocket:
        with testClient.websocket_connect("/ws?user_id=user-a") as new_websocket:
            if old_connection_first:
                first_websocket = old_websocket
                second_websocket = new_websocket
            else:
                first_websocket = new_websocket
                second_websocket = old_websocket

            first_websocket.close()
            second_websocket.close()

    assert connectionManager._connections == {}

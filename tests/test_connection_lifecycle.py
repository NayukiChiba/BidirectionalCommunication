"""
WebSocket 连接生命周期验收测试
"""

import pytest
from fastapi.testclient import TestClient

from main import app, manager

test_client = TestClient(app)


# TODO(Issue 08 - 重复登录接口验收): 用同一 user_id 依次建立两个 WebSocket；
# 断言旧连接以 4001 和固定原因关闭，新连接仍能收发消息，旧连接退出不影响新连接。

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

"""WebSocket 连接生命周期验收测试。"""

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from tests.conftest import AuthenticatedTestUser


def test_duplicate_login_replaces_old_connection(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """同一令牌重复连接时，新连接替换旧连接。"""
    clientMessageId = "819145f5-5ddb-4ae1-a382-f81fb81e6f08"
    user = authenticatedUsers["user-a"]
    connectionManager = application.state.connection_manager

    with testClient.websocket_connect(
        "/ws",
        headers=user.authorizationHeaders,
    ) as oldWebSocket:
        with testClient.websocket_connect(
            "/ws",
            headers=user.authorizationHeaders,
        ) as newWebSocket:
            with pytest.raises(WebSocketDisconnect) as exceptionInfo:
                oldWebSocket.receive_text()

            assert exceptionInfo.value.code == 4001
            assert exceptionInfo.value.reason == "该账号已在其他连接登录"

            oldWebSocket.close()
            assert connectionManager.is_online(user.userId) is True

            newWebSocket.send_json(
                {
                    "type": "send_message",
                    "conversation_id": conversationId,
                    "content": "新连接仍然可用",
                    "client_message_id": clientMessageId,
                }
            )
            acceptedEvent = newWebSocket.receive_json()

            assert acceptedEvent["type"] == "accepted"
            assert acceptedEvent["push_status"] == "recipient_offline"

    assert connectionManager.is_online(user.userId) is False


@pytest.mark.parametrize(
    ("firstUsername", "secondUsername"),
    [
        pytest.param("user-a", "user-b", id="user-a-first"),
        pytest.param("user-b", "user-a", id="user-b-first"),
    ],
)
def test_disconnect_users_in_any_order(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    firstUsername: str,
    secondUsername: str,
) -> None:
    """两个已认证用户按任意顺序断开后应清空连接表。"""
    connectionManager = application.state.connection_manager
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    with testClient.websocket_connect(
        "/ws",
        headers=userA.authorizationHeaders,
    ) as userAWebSocket:
        with testClient.websocket_connect(
            "/ws",
            headers=userB.authorizationHeaders,
        ) as userBWebSocket:
            assert connectionManager.is_online(userA.userId) is True
            assert connectionManager.is_online(userB.userId) is True

            webSockets = {
                "user-a": userAWebSocket,
                "user-b": userBWebSocket,
            }
            webSockets[firstUsername].close()
            webSockets[secondUsername].close()

    assert connectionManager._connections == {}


@pytest.mark.parametrize(
    "oldConnectionFirst",
    [
        pytest.param(True, id="old-connection-first"),
        pytest.param(False, id="new-connection-first"),
    ],
)
def test_disconnect_replaced_connections_in_any_order(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    oldConnectionFirst: bool,
) -> None:
    """同一身份的新旧连接按任意顺序退出后应清空连接表。"""
    connectionManager = application.state.connection_manager
    user = authenticatedUsers["user-a"]

    with testClient.websocket_connect(
        "/ws",
        headers=user.authorizationHeaders,
    ) as oldWebSocket:
        with testClient.websocket_connect(
            "/ws",
            headers=user.authorizationHeaders,
        ) as newWebSocket:
            if oldConnectionFirst:
                firstWebSocket = oldWebSocket
                secondWebSocket = newWebSocket
            else:
                firstWebSocket = newWebSocket
                secondWebSocket = oldWebSocket

            firstWebSocket.close()
            secondWebSocket.close()

    assert connectionManager._connections == {}

"""注册、登录、HTTP Bearer 与 WebSocket 握手鉴权验收测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.adapters.database.migrationConfig import createMigrationEngine
from src.config import JWT_ALGORITHM
from tests.conftest import TEST_AUTH_SECRET, TEST_PASSWORD, AuthenticatedTestUser


def registerUser(
    testClient: TestClient,
    *,
    username: str,
    password: str = TEST_PASSWORD,
) -> dict[str, str]:
    """调用真实注册接口并返回身份响应。"""
    response = testClient.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def createSignedToken(payload: dict[str, object]) -> str:
    """使用测试密钥创建指定声明的 JWT。"""
    return jwt.encode(payload, TEST_AUTH_SECRET, algorithm=JWT_ALGORITHM)


def test_register_login_and_me_share_same_identity(testClient: TestClient) -> None:
    """注册、登录和 Bearer 当前用户应指向同一稳定用户。"""
    identity = registerUser(testClient, username="Alice")

    login = testClient.post(
        "/auth/token",
        data={"username": "ALICE", "password": TEST_PASSWORD},
    )
    tokenBody = login.json()
    currentUser = testClient.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokenBody['access_token']}"},
    )

    assert login.status_code == 200
    assert tokenBody["token_type"] == "bearer"
    assert datetime.fromisoformat(tokenBody["expires_at"]).tzinfo is not None
    assert identity["username"] == "alice"
    assert currentUser.status_code == 200
    assert currentUser.json() == identity
    assert "password" not in identity
    assert "password_hash" not in identity


def test_registration_stores_hash_and_handles_normalized_conflict(
    testClient: TestClient,
    application: FastAPI,
) -> None:
    """数据库不能保存明文密码，大小写变化也不能绕过用户名唯一性。"""
    identity = registerUser(testClient, username="Alice")
    duplicate = testClient.post(
        "/auth/register",
        json={"username": " alice ", "password": TEST_PASSWORD},
    )

    databasePath = Path(application.state.database_engine.url.database)
    engine = createMigrationEngine(databasePath)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT user_id, username, password_hash "
                    "FROM users WHERE user_id = :userId"
                ),
                {"userId": identity["user_id"]},
            ).one()
            columns = {
                column[1]
                for column in connection.exec_driver_sql("PRAGMA table_info(users)")
            }
    finally:
        engine.dispose()

    assert duplicate.status_code == 409
    assert row.username == "alice"
    assert row.password_hash.startswith("$argon2id$")
    assert row.password_hash != TEST_PASSWORD
    assert "password" not in columns
    assert "password_hash" in columns


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("alice", "wrong password with enough length"),
        ("missing-user", "wrong password with enough length"),
    ],
)
def test_login_uses_same_error_for_invalid_credentials(
    testClient: TestClient,
    username: str,
    password: str,
) -> None:
    """错误密码和不存在用户不应泄露不同错误。"""
    registerUser(testClient, username="alice")

    response = testClient.post(
        "/auth/token",
        data={"username": username, "password": password},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "无法验证身份凭证"


@pytest.mark.parametrize("token", [None, "invalid-token"])
def test_http_rejects_missing_or_invalid_token(
    testClient: TestClient,
    token: str | None,
) -> None:
    """受保护 HTTP 接口必须拒绝无令牌和非法令牌。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    meResponse = testClient.get("/auth/me", headers=headers)
    historyResponse = testClient.get(
        "/messages/history",
        params={"peer_id": str(uuid4())},
        headers=headers,
    )

    assert meResponse.status_code == 401
    assert historyResponse.status_code == 401


def test_http_and_websocket_reject_expired_token(testClient: TestClient) -> None:
    """签名正确但已经过期的令牌不能建立任何身份。"""
    now = datetime.now(timezone.utc)
    expiredToken = createSignedToken(
        {
            "sub": str(uuid4()),
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=15),
        }
    )
    headers = {"Authorization": f"Bearer {expiredToken}"}

    assert testClient.get("/auth/me", headers=headers).status_code == 401
    with pytest.raises(WebSocketDisconnect) as exceptionInfo:
        with testClient.websocket_connect("/ws", headers=headers):
            pass
    assert exceptionInfo.value.code == 4401


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-token"}])
def test_websocket_rejects_missing_or_invalid_token(
    testClient: TestClient,
    headers: dict[str, str],
) -> None:
    """WebSocket 必须在登记连接前拒绝无效握手凭证。"""
    with pytest.raises(WebSocketDisconnect) as exceptionInfo:
        with testClient.websocket_connect("/ws", headers=headers):
            pass

    assert exceptionInfo.value.code == 4401


def test_websocket_ignores_forged_query_identity(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """查询参数不能覆盖 Bearer 令牌中的发送者身份。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    connectionManager = application.state.connection_manager

    with testClient.websocket_connect(
        f"/ws?user_id={userB.userId}",
        headers=userA.authorizationHeaders,
    ) as webSocket:
        assert connectionManager.is_online(userA.userId) is True
        assert connectionManager.is_online(userB.userId) is False
        webSocket.send_json(
            {
                "type": "send_message",
                "recipient_id": userA.userId,
                "content": "trusted sender",
                "client_message_id": str(uuid4()),
            }
        )
        messageEvent = webSocket.receive_json()
        acknowledgement = webSocket.receive_json()

    assert messageEvent["sender_id"] == userA.userId
    assert acknowledgement["server_message_id"] == messageEvent["server_message_id"]

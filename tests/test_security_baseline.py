"""WebSocket 资源限制与认证响应安全基线测试。"""

from pathlib import Path

import pytest
from alembic import command
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from bootstrap import create_app
from src.adapters.database.migrationConfig import createMigrationConfig
from src.config import AuthSettings, RuntimeSettings
from tests.conftest import TEST_AUTH_SECRET, TEST_PASSWORD


def createLimitedClient(databasePath: Path) -> TestClient:
    """创建使用较小限制、便于确定性测试的真实应用。"""
    command.upgrade(createMigrationConfig(databasePath), "head")
    app = create_app(
        databasePath=databasePath,
        authSettings=AuthSettings(secretKey=TEST_AUTH_SECRET),
        runtimeSettings=RuntimeSettings(
            maxWebSocketMessageBytes=1_024,
            inputRateLimitCount=2,
            inputRateLimitWindowSeconds=60,
            maxWebSocketConnections=10,
        ),
    )
    return TestClient(app)


def registerAndLogin(client: TestClient) -> dict[str, str]:
    """返回资源限制测试使用的 Bearer 请求头。"""
    registration = client.post(
        "/auth/register",
        json={"username": "limited-user", "password": TEST_PASSWORD},
    )
    login = client.post(
        "/auth/token",
        data={"username": "limited-user", "password": TEST_PASSWORD},
    )
    assert registration.status_code == 201
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_oversized_websocket_message_is_rejected_and_connection_closed(
    tmp_path: Path,
) -> None:
    """超过字节上限的载荷不能进入 JSON 或业务处理。"""
    with createLimitedClient(tmp_path / "oversized.sqlite3") as client:
        headers = registerAndLogin(client)
        with client.websocket_connect("/ws", headers=headers) as websocket:
            websocket.send_text("x" * 1_025)
            errorEvent = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as exceptionInfo:
                websocket.receive_text()

    assert errorEvent["code"] == "message_too_large"
    assert exceptionInfo.value.code == 4409


def test_high_frequency_websocket_input_is_rejected_without_sleep(
    tmp_path: Path,
) -> None:
    """单连接滑动窗口超限时返回稳定错误并主动关闭连接。"""
    with createLimitedClient(tmp_path / "rate-limit.sqlite3") as client:
        headers = registerAndLogin(client)
        with client.websocket_connect("/ws", headers=headers) as websocket:
            for _ in range(2):
                websocket.send_json({"type": "unknown"})
                assert websocket.receive_json()["code"] == "invalid_message"
            websocket.send_json({"type": "unknown"})
            errorEvent = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as exceptionInfo:
                websocket.receive_text()

    assert errorEvent["code"] == "rate_limited"
    assert exceptionInfo.value.code == 4408


@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_websocket_authentication_rejections_do_not_reveal_reason(
    testClient: TestClient,
    authorization: str | None,
) -> None:
    """缺失和非法凭证使用相同关闭码及外部原因。"""
    headers = {"Authorization": authorization} if authorization else {}

    with pytest.raises(WebSocketDisconnect) as exceptionInfo:
        with testClient.websocket_connect("/ws", headers=headers):
            pass

    assert exceptionInfo.value.code == 4401
    assert exceptionInfo.value.reason == "无法验证身份凭证"

"""外部行为测试共享的隔离应用夹具。"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bootstrap import create_app
from src.adapters.database.migrationConfig import createMigrationConfig
from src.config import AuthSettings

TEST_AUTH_SECRET = "test-auth-secret-" + ("x" * 64)
TEST_PASSWORD = "correct horse battery staple"


@dataclass(frozen=True, slots=True)
class AuthenticatedTestUser:
    """外部行为测试使用的已注册登录用户。"""

    userId: str
    username: str
    accessToken: str

    @property
    def authorizationHeaders(self) -> dict[str, str]:
        """返回 HTTP 和 WebSocket 握手共用的 Bearer 头。"""
        return {"Authorization": f"Bearer {self.accessToken}"}


@pytest.fixture
def authSettings() -> AuthSettings:
    """创建不读取真实环境密钥的测试认证配置。"""
    return AuthSettings(secretKey=TEST_AUTH_SECRET)


@pytest.fixture
def application(tmp_path: Path, authSettings: AuthSettings) -> FastAPI:
    """为每个测试创建使用独立 SQLite 文件的应用。"""
    databasePath = tmp_path / "application.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    return create_app(databasePath=databasePath, authSettings=authSettings)


@pytest.fixture
def testClient(application: FastAPI) -> Iterator[TestClient]:
    """启动应用生命周期并在测试结束后释放资源。"""
    with TestClient(application) as client:
        yield client


@pytest.fixture
def authenticatedUsers(
    testClient: TestClient,
) -> dict[str, AuthenticatedTestUser]:
    """注册并登录外部行为测试常用的两个用户。"""
    users: dict[str, AuthenticatedTestUser] = {}
    for username in ("user-a", "user-b"):
        registration = testClient.post(
            "/auth/register",
            json={"username": username, "password": TEST_PASSWORD},
        )
        assert registration.status_code == 201
        identity = registration.json()
        login = testClient.post(
            "/auth/token",
            data={"username": username, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        users[username] = AuthenticatedTestUser(
            userId=identity["user_id"],
            username=identity["username"],
            accessToken=login.json()["access_token"],
        )
    return users

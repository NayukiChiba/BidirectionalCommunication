"""存活、就绪与请求关联 ID 接口测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from bootstrap import create_app
from src.config import AuthSettings, RuntimeSettings


def test_liveness_does_not_depend_on_database(testClient: TestClient) -> None:
    """存活检查只判断进程能否响应，并返回关联 ID。"""
    response = testClient.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["x-request-id"]
    assert (
        testClient.get("/health/live").headers["x-request-id"]
        != response.headers["x-request-id"]
    )


def test_compatibility_health_is_liveness(testClient: TestClient) -> None:
    """旧健康路径保持为存活检查别名。"""
    response = testClient.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_requires_expected_database_revision(testClient: TestClient) -> None:
    """迁移完成的数据库才可以承接业务流量。"""
    response = testClient.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_unmigrated_database_is_alive_but_not_ready(tmp_path: Path) -> None:
    """数据库未迁移不应导致进程重启，但应从流量中摘除。"""
    app = create_app(
        databasePath=tmp_path / "unmigrated.sqlite3",
        authSettings=AuthSettings(secretKey="x" * 64),
        runtimeSettings=RuntimeSettings(),
    )

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        readiness = client.get("/health/ready")

    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}

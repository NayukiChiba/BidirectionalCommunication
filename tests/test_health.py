"""健康检查接口测试。"""

from fastapi.testclient import TestClient

from main import app

test_client = TestClient(app)


def test_get_health() -> None:
    """测试健康检查接口"""
    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

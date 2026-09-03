"""健康检查接口测试。"""

from fastapi.testclient import TestClient


def test_get_health(testClient: TestClient) -> None:
    """测试健康检查接口"""
    response = testClient.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

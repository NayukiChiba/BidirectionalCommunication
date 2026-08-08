"""应用组合根测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bootstrap import create_app


def test_create_app_composes_dependencies_and_routes() -> None:
    """组合根应返回具有完整依赖和路由的 FastAPI 应用。"""
    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.state.connection_manager is not None
    assert app.state.message_repository is not None
    assert app.state.message_notifier is not None
    assert app.state.send_message_service is not None
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_create_app_returns_independent_compositions() -> None:
    """每次组合都应创建独立的可运行对象图。"""
    first_app = create_app()
    second_app = create_app()

    assert first_app.state.connection_manager is not second_app.state.connection_manager
    assert (
        first_app.state.send_message_service
        is not second_app.state.send_message_service
    )

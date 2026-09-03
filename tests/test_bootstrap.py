"""应用组合根测试。"""

from pathlib import Path

from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from bootstrap import create_app
from src.adapters.database.migrationConfig import createMigrationConfig


def test_create_app_composes_dependencies_and_routes(tmp_path: Path) -> None:
    """组合根应返回具有完整依赖和路由的 FastAPI 应用。"""
    databasePath = tmp_path / "bootstrap.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    app = create_app(databasePath=databasePath)

    assert isinstance(app, FastAPI)
    assert app.state.connection_manager is not None
    assert app.state.database_engine is not None
    assert app.state.session_factory is not None
    assert app.state.unit_of_work_factory is not None
    assert app.state.message_notifier is not None
    assert app.state.send_message_service is not None
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert inspect(app.state.database_engine).has_table("messages")


def test_app_startup_does_not_create_database_schema(tmp_path: Path) -> None:
    """应用启动不能替代显式 Alembic 迁移。"""
    app = create_app(databasePath=tmp_path / "unmigrated.sqlite3")

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert inspect(app.state.database_engine).get_table_names() == []


def test_create_app_returns_independent_compositions(tmp_path: Path) -> None:
    """每次组合都应创建独立的可运行对象图。"""
    first_app = create_app(databasePath=tmp_path / "first.sqlite3")
    second_app = create_app(databasePath=tmp_path / "second.sqlite3")

    assert first_app.state.connection_manager is not second_app.state.connection_manager
    assert first_app.state.database_engine is not second_app.state.database_engine
    assert (
        first_app.state.send_message_service
        is not second_app.state.send_message_service
    )

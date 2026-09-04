"""应用组合根测试。"""

from pathlib import Path

from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from bootstrap import create_app
from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)
from src.config import AuthSettings

TEST_AUTH_SECRET = "test-auth-secret-" + ("x" * 64)


def createTestAuthSettings() -> AuthSettings:
    """创建不依赖开发环境变量的认证配置。"""
    return AuthSettings(secretKey=TEST_AUTH_SECRET)


def test_create_app_composes_dependencies_and_routes(tmp_path: Path) -> None:
    """组合根应返回具有完整依赖和路由的 FastAPI 应用。"""
    databasePath = tmp_path / "bootstrap.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    app = create_app(
        databasePath=databasePath,
        authSettings=createTestAuthSettings(),
    )

    assert isinstance(app, FastAPI)
    assert app.state.connection_manager is not None
    assert isinstance(app.state.database_engine, AsyncEngine)
    assert app.state.session_factory is not None
    assert app.state.unit_of_work_factory is not None
    assert app.state.conversation_unit_of_work_factory is not None
    assert app.state.message_notifier is not None
    assert app.state.send_message_service is not None
    assert app.state.history_service is not None
    assert app.state.authentication_service is not None
    assert app.state.conversation_service is not None
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        inspectionEngine = createMigrationEngine(databasePath)
        try:
            assert inspect(inspectionEngine).has_table("messages")
            assert inspect(inspectionEngine).has_table("users")
            assert inspect(inspectionEngine).has_table("conversations")
            assert inspect(inspectionEngine).has_table("conversation_members")
        finally:
            inspectionEngine.dispose()


def test_app_startup_does_not_create_database_schema(tmp_path: Path) -> None:
    """应用启动不能替代显式 Alembic 迁移。"""
    databasePath = tmp_path / "unmigrated.sqlite3"
    app = create_app(
        databasePath=databasePath,
        authSettings=createTestAuthSettings(),
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    inspectionEngine = createMigrationEngine(databasePath)
    try:
        assert inspect(inspectionEngine).get_table_names() == []
    finally:
        inspectionEngine.dispose()


def test_create_app_returns_independent_compositions(tmp_path: Path) -> None:
    """每次组合都应创建独立的可运行对象图。"""
    first_app = create_app(
        databasePath=tmp_path / "first.sqlite3",
        authSettings=createTestAuthSettings(),
    )
    second_app = create_app(
        databasePath=tmp_path / "second.sqlite3",
        authSettings=createTestAuthSettings(),
    )

    assert first_app.state.connection_manager is not second_app.state.connection_manager
    assert first_app.state.database_engine is not second_app.state.database_engine
    assert (
        first_app.state.send_message_service
        is not second_app.state.send_message_service
    )

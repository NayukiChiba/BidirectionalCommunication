"""外部行为测试共享的隔离应用夹具。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bootstrap import create_app
from src.adapters.database.migrationConfig import createMigrationConfig


@pytest.fixture
def application(tmp_path: Path) -> FastAPI:
    """为每个测试创建使用独立 SQLite 文件的应用。"""
    databasePath = tmp_path / "application.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    return create_app(databasePath=databasePath)


@pytest.fixture
def testClient(application: FastAPI) -> Iterator[TestClient]:
    """启动应用生命周期并在测试结束后释放资源。"""
    with TestClient(application) as client:
        yield client

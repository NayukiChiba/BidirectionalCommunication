"""异步用户 Repository 和 Unit of Work 集成测试。"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.adapters.database import (
    AsyncSqlAlchemyUserUnitOfWorkFactory,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.application import UsernameAlreadyExists
from src.domain import PasswordHash, Username, createUser


@pytest_asyncio.fixture
async def databaseEngine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """创建包含用户表的隔离异步数据库。"""
    databasePath = tmp_path / "users.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createAsyncSqliteEngine(databasePath)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def userUnitOfWorkFactory(
    databaseEngine: AsyncEngine,
) -> AsyncSqlAlchemyUserUnitOfWorkFactory:
    """创建每次调用产生独立 AsyncSession 的用户 UoW 工厂。"""
    sessionFactory: async_sessionmaker[AsyncSession] = createAsyncSessionFactory(
        databaseEngine
    )
    return AsyncSqlAlchemyUserUnitOfWorkFactory(sessionFactory)


@pytest.mark.asyncio
async def test_user_repository_round_trip_contains_only_password_hash(
    userUnitOfWorkFactory: AsyncSqlAlchemyUserUnitOfWorkFactory,
) -> None:
    """保存并读取用户时应保留身份和哈希，不存在明文密码字段。"""
    user = createUser(
        username=Username("alice"),
        passwordHash=PasswordHash("$argon2id$stored-hash"),
    )

    async with userUnitOfWorkFactory() as unitOfWork:
        await unitOfWork.users.add(user)
        await unitOfWork.commit()

    async with userUnitOfWorkFactory() as unitOfWork:
        byUsername = await unitOfWork.users.getByUsername(Username("ALICE"))
        byId = await unitOfWork.users.getById(user.user_id)

    assert byUsername == user
    assert byId == user
    assert byUsername is not None
    assert byUsername.password_hash == user.password_hash
    assert not hasattr(byUsername, "password")


@pytest.mark.asyncio
async def test_database_unique_constraint_handles_concurrent_username_race(
    userUnitOfWorkFactory: AsyncSqlAlchemyUserUnitOfWorkFactory,
) -> None:
    """应用预查之后仍由数据库唯一约束阻止重复用户名。"""
    firstUser = createUser(
        username=Username("alice"),
        passwordHash=PasswordHash("first-hash"),
    )
    duplicateUser = createUser(
        username=Username("ALICE"),
        passwordHash=PasswordHash("second-hash"),
    )

    async with userUnitOfWorkFactory() as unitOfWork:
        await unitOfWork.users.add(firstUser)
        await unitOfWork.commit()

    with pytest.raises(UsernameAlreadyExists):
        async with userUnitOfWorkFactory() as unitOfWork:
            await unitOfWork.users.add(duplicateUser)
            await unitOfWork.commit()

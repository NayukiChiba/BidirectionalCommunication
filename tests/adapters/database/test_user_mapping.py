"""用户 ORM 映射和领域转换测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from src.adapters.database import UserRecord, toDomainUser, toUserRecord
from src.adapters.database.migrationConfig import (
    createMigrationConfig,
    createMigrationEngine,
)
from src.domain import PasswordHash, User, UserId, Username


def createUserSample() -> User:
    """创建固定用户领域样本。"""
    return User(
        user_id=UserId("10000000-0000-0000-0000-000000000001"),
        username=Username("Alice"),
        password_hash=PasswordHash("$argon2id$stored-hash"),
        created_at=datetime(
            2026,
            9,
            4,
            12,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )


def test_user_table_contains_identity_username_and_hash_constraints(
    tmp_path: Path,
) -> None:
    """用户表只能保存身份、规范化用户名、哈希和创建时间。"""
    databasePath = tmp_path / "user-schema.sqlite3"
    command.upgrade(createMigrationConfig(databasePath), "head")
    engine = createMigrationEngine(databasePath)
    try:
        inspector = inspect(engine)
        assert {column["name"] for column in inspector.get_columns("users")} == {
            "user_id",
            "username",
            "password_hash",
            "created_at",
        }
        assert inspector.get_pk_constraint("users")["constrained_columns"] == [
            "user_id"
        ]
        assert {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints("users")
        } == {("uq_users_username", ("username",))}
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints("users")
        } == {
            "ck_users_password_hash_not_blank",
            "ck_users_user_id_length",
            "ck_users_username_length",
            "ck_users_username_normalized",
        }
    finally:
        engine.dispose()


def test_user_conversion_round_trip_hides_plain_password_concept() -> None:
    """用户转换应保持字段且不存在明文密码属性。"""
    user = createUserSample()

    record = toUserRecord(user)
    restoredUser = toDomainUser(record)

    assert isinstance(record, UserRecord)
    assert restoredUser == user
    assert restoredUser.username == user.username
    assert restoredUser.password_hash == user.password_hash
    assert restoredUser.created_at == user.created_at
    assert not hasattr(record, "password")

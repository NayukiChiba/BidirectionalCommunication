"""用户领域模型测试。"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.domain import (
    InvalidPasswordHash,
    InvalidUsername,
    PasswordHash,
    UserId,
    Username,
    createUser,
)


def test_username_normalizes_case_and_whitespace() -> None:
    """用户名应规范化为无首尾空白的小写文本。"""
    assert Username("  Alice.SMITH  ") == Username("alice.smith")


@pytest.mark.parametrize(
    "value",
    ["ab", "a" * 33, "user name", "用户", "admin@site"],
)
def test_username_rejects_invalid_values(value: str) -> None:
    """用户名只允许规定长度的 ASCII 安全字符。"""
    with pytest.raises(InvalidUsername):
        Username(value)


def test_password_hash_rejects_blank_value() -> None:
    """领域层不能接受空密码哈希。"""
    with pytest.raises(InvalidPasswordHash):
        PasswordHash("   ")


def test_created_user_has_uuid_identity_utc_time_and_hidden_hash() -> None:
    """用户应具有稳定身份、UTC 时间且 repr 不暴露密码哈希。"""
    passwordHash = PasswordHash("$argon2id$secret-hash")
    user = createUser(username=Username("alice"), passwordHash=passwordHash)

    assert user.user_id.value != "alice"
    assert user.created_at.tzinfo is timezone.utc
    assert "$argon2id$secret-hash" not in repr(user)


def test_user_normalizes_aware_time_and_is_immutable() -> None:
    """用户创建时间应转为 UTC，实体字段不能被修改。"""
    createdAt = datetime(
        2026,
        9,
        4,
        12,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    user = createUser(
        username=Username("alice"),
        passwordHash=PasswordHash("hash"),
    )
    normalizedUser = type(user)(
        user_id=UserId(user.user_id.value),
        username=user.username,
        password_hash=user.password_hash,
        created_at=createdAt,
    )

    assert normalizedUser.created_at == datetime(
        2026,
        9,
        4,
        4,
        0,
        tzinfo=timezone.utc,
    )
    with pytest.raises(FrozenInstanceError):
        normalizedUser.username = Username("other")  # type: ignore[misc]

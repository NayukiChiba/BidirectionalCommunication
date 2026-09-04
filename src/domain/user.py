"""纯 Python 用户领域模型。"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.exceptions import (
    InvalidPasswordHash,
    InvalidUser,
    InvalidUsername,
)
from src.domain.message import UserId

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class Username:
    """规范化为小写 ASCII 的登录用户名。"""

    value: str

    def __post_init__(self) -> None:
        """去除首尾空白并验证用户名。"""
        if not isinstance(self.value, str):
            raise InvalidUsername("用户名必须是字符串")
        normalizedValue = self.value.strip().casefold()
        if not MIN_USERNAME_LENGTH <= len(normalizedValue) <= MAX_USERNAME_LENGTH:
            raise InvalidUsername(
                f"用户名长度必须在 {MIN_USERNAME_LENGTH} 到 {MAX_USERNAME_LENGTH} 之间"
            )
        if USERNAME_PATTERN.fullmatch(normalizedValue) is None:
            raise InvalidUsername("用户名只能包含小写字母、数字、点、下划线和连字符")
        object.__setattr__(self, "value", normalizedValue)

    def __str__(self) -> str:
        """返回规范化用户名。"""
        return self.value


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """由专用密码库生成的不可逆密码哈希。"""

    value: str

    def __post_init__(self) -> None:
        """拒绝空白或非字符串哈希。"""
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvalidPasswordHash("密码哈希必须是非空字符串")

    def __str__(self) -> str:
        """仅供持久化边界显式转换。"""
        return self.value


@dataclass(frozen=True, eq=False, slots=True)
class User:
    """通过稳定用户 ID 维持身份的用户实体。"""

    user_id: UserId
    username: Username
    password_hash: PasswordHash = field(repr=False)
    created_at: datetime

    def __post_init__(self) -> None:
        """验证用户组合并统一创建时间为 UTC。"""
        if not isinstance(self.user_id, UserId):
            raise InvalidUser("user_id 必须是 UserId")
        if not isinstance(self.username, Username):
            raise InvalidUser("username 必须是 Username")
        if not isinstance(self.password_hash, PasswordHash):
            raise InvalidUser("password_hash 必须是 PasswordHash")
        if not isinstance(self.created_at, datetime):
            raise InvalidUser("created_at 必须是 datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidUser("用户创建时间必须包含时区")
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )

    def __eq__(self, other: object) -> bool:
        """通过用户 ID 判断实体身份。"""
        return isinstance(other, User) and self.user_id == other.user_id

    def __hash__(self) -> int:
        """使用稳定用户 ID 计算哈希。"""
        return hash(self.user_id)


def createUser(*, username: Username, passwordHash: PasswordHash) -> User:
    """创建具有 UUID 身份和 UTC 时间的用户。"""
    return User(
        user_id=UserId(str(uuid4())),
        username=username,
        password_hash=passwordHash,
        created_at=datetime.now(timezone.utc),
    )

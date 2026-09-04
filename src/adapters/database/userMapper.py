"""用户领域实体与 ORM 用户记录之间的显式转换。"""

from datetime import datetime, timezone

from src.adapters.database.models import UserRecord
from src.domain import PasswordHash, User, UserId, Username


def toUserRecord(user: User) -> UserRecord:
    """将用户实体转换为不包含明文密码的 ORM 记录。"""
    return UserRecord(
        userId=str(user.user_id),
        username=str(user.username),
        passwordHash=str(user.password_hash),
        createdAt=user.created_at,
    )


def toDomainUser(record: UserRecord) -> User:
    """将 ORM 记录转换为重新验证不变量的用户实体。"""
    return User(
        user_id=UserId(record.userId),
        username=Username(record.username),
        password_hash=PasswordHash(record.passwordHash),
        created_at=normalizeUserDatetime(record.createdAt),
    )


def normalizeUserDatetime(value: datetime) -> datetime:
    """把 SQLite 返回的无时区创建时间解释为 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

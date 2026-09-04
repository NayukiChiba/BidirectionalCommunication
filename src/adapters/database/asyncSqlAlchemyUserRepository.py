"""基于 AsyncSession 的用户 Repository。"""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models import UserRecord
from src.adapters.database.userMapper import toDomainUser, toUserRecord
from src.application.exceptions import UserStorageError
from src.domain import User, UserId, Username


class AsyncSqlAlchemyUserRepository:
    """通过当前 AsyncSession 保存和查询认证用户。"""

    def __init__(self, session: AsyncSession) -> None:
        """接收由用户工作单元管理的 AsyncSession。"""
        self._session = session

    async def add(self, user: User) -> None:
        """加入只包含密码哈希的用户 ORM 记录。"""
        try:
            self._session.add(toUserRecord(user))
        except SQLAlchemyError as error:
            raise UserStorageError("用户加入数据库会话失败") from error

    async def getByUsername(self, username: Username) -> User | None:
        """按数据库唯一的规范化用户名查询用户。"""
        statement = select(UserRecord).where(UserRecord.username == str(username))
        try:
            record = (await self._session.scalars(statement)).one_or_none()
        except SQLAlchemyError as error:
            raise UserStorageError("按用户名查询用户失败") from error
        return toDomainUser(record) if record is not None else None

    async def getById(self, userId: UserId) -> User | None:
        """按稳定用户 ID 查询用户。"""
        statement = select(UserRecord).where(UserRecord.userId == str(userId))
        try:
            record = (await self._session.scalars(statement)).one_or_none()
        except SQLAlchemyError as error:
            raise UserStorageError("按用户 ID 查询用户失败") from error
        return toDomainUser(record) if record is not None else None

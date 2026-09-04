"""用户认证依赖的密码、令牌、存储和事务端口。"""

from types import TracebackType
from typing import Protocol

from src.application.authModels import AccessToken
from src.domain import PasswordHash, User, UserId, Username


class PasswordHasher(Protocol):
    """专用密码哈希库提供的最小能力。"""

    async def hashPassword(self, plainPassword: str) -> PasswordHash:
        """使用随机盐和慢哈希生成密码哈希。"""
        ...

    async def verifyPassword(
        self,
        plainPassword: str,
        passwordHash: PasswordHash | None,
    ) -> bool:
        """验证密码；用户不存在时也执行固定假哈希验证。"""
        ...


class AccessTokenProvider(Protocol):
    """短期访问令牌的签发和验证能力。"""

    def createAccessToken(self, userId: UserId) -> AccessToken:
        """为用户签发带 sub、iat 和 exp 的令牌。"""
        ...

    def getUserId(self, token: str) -> UserId:
        """验证令牌并返回可信用户 ID。"""
        ...


class UserRepository(Protocol):
    """认证用例所需的最小用户存储语义。"""

    async def add(self, user: User) -> None:
        """加入一个新用户。"""
        ...

    async def getByUsername(self, username: Username) -> User | None:
        """按规范化用户名查找用户。"""
        ...

    async def getById(self, userId: UserId) -> User | None:
        """按稳定用户 ID 查找用户。"""
        ...


class UserUnitOfWork(Protocol):
    """一次用户认证操作的原子事务边界。"""

    users: UserRepository

    async def __aenter__(self) -> "UserUnitOfWork":
        """创建独立用户事务和 Repository。"""
        ...

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """默认回滚并释放数据库资源。"""
        ...

    async def commit(self) -> None:
        """显式提交用户事务。"""
        ...

    async def rollback(self) -> None:
        """回滚用户事务。"""
        ...


class UserUnitOfWorkFactory(Protocol):
    """为每次认证用例创建独立用户工作单元。"""

    def __call__(self) -> UserUnitOfWork:
        """创建尚未进入事务范围的用户工作单元。"""
        ...

"""用户注册、登录和令牌认证应用服务测试。"""

from datetime import datetime, timedelta, timezone
from types import TracebackType

import pytest

from src.application import (
    AccessToken,
    AuthenticationService,
    InvalidAccessToken,
    InvalidCredentials,
    InvalidRegistration,
    LoginCommand,
    RegisterUserCommand,
    UsernameAlreadyExists,
)
from src.domain import PasswordHash, User, UserId, Username


class FakeUserRepository:
    """使用共享列表实现最小用户 Repository。"""

    def __init__(self, users: list[User]) -> None:
        self.users = users

    async def add(self, user: User) -> None:
        self.users.append(user)

    async def getByUsername(self, username: Username) -> User | None:
        return next((user for user in self.users if user.username == username), None)

    async def getById(self, userId: UserId) -> User | None:
        return next((user for user in self.users if user.user_id == userId), None)


class FakeUserUnitOfWork:
    """支持显式提交和默认回滚的用户工作单元。"""

    def __init__(
        self,
        committedUsers: list[User],
        commitError: Exception | None = None,
    ) -> None:
        self._committedUsers = committedUsers
        self._workingUsers = list(committedUsers)
        self._commitError = commitError
        self.users = FakeUserRepository(self._workingUsers)
        self.committed = False

    async def __aenter__(self) -> "FakeUserUnitOfWork":
        return self

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exceptionType is not None or not self.committed:
            await self.rollback()

    async def commit(self) -> None:
        if self._commitError is not None:
            raise self._commitError
        self._committedUsers[:] = self._workingUsers
        self.committed = True

    async def rollback(self) -> None:
        self._workingUsers[:] = self._committedUsers


class FakeUserUnitOfWorkFactory:
    """创建共享已提交用户状态的独立工作单元。"""

    def __init__(self, commitError: Exception | None = None) -> None:
        self.users: list[User] = []
        self.commitError = commitError
        self.createdUnits: list[FakeUserUnitOfWork] = []

    def __call__(self) -> FakeUserUnitOfWork:
        unitOfWork = FakeUserUnitOfWork(self.users, self.commitError)
        self.createdUnits.append(unitOfWork)
        return unitOfWork


class FakePasswordHasher:
    """记录明文仅供应用单元测试验证调用。"""

    def __init__(self) -> None:
        self.hashedPasswords: list[str] = []
        self.verifications: list[tuple[str, PasswordHash | None]] = []

    async def hashPassword(self, plainPassword: str) -> PasswordHash:
        self.hashedPasswords.append(plainPassword)
        return PasswordHash(f"hashed:{plainPassword}")

    async def verifyPassword(
        self,
        plainPassword: str,
        passwordHash: PasswordHash | None,
    ) -> bool:
        self.verifications.append((plainPassword, passwordHash))
        return passwordHash == PasswordHash(f"hashed:{plainPassword}")


class FakeAccessTokenProvider:
    """为应用测试签发和解析固定格式令牌。"""

    def createAccessToken(self, userId: UserId) -> AccessToken:
        return AccessToken(
            value=f"token:{userId}",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

    def getUserId(self, token: str) -> UserId:
        if not token.startswith("token:"):
            raise InvalidAccessToken("无效测试令牌")
        return UserId(token.removeprefix("token:"))


def createService(
    unitOfWorkFactory: FakeUserUnitOfWorkFactory,
    passwordHasher: FakePasswordHasher | None = None,
) -> tuple[AuthenticationService, FakePasswordHasher]:
    """创建使用假端口的认证服务。"""
    resolvedHasher = passwordHasher or FakePasswordHasher()
    return (
        AuthenticationService(
            userUnitOfWorkFactory=unitOfWorkFactory,
            passwordHasher=resolvedHasher,
            accessTokenProvider=FakeAccessTokenProvider(),
        ),
        resolvedHasher,
    )


@pytest.mark.asyncio
async def test_register_normalizes_username_and_stores_only_hash() -> None:
    """注册应规范化用户名并在提交前把明文替换为哈希。"""
    unitOfWorkFactory = FakeUserUnitOfWorkFactory()
    service, passwordHasher = createService(unitOfWorkFactory)

    identity = await service.register(
        RegisterUserCommand(
            username="  Alice  ",
            password="correct horse battery staple",
        )
    )

    storedUser = unitOfWorkFactory.users[0]
    assert identity.username == Username("alice")
    assert storedUser.password_hash == PasswordHash(
        "hashed:correct horse battery staple"
    )
    assert storedUser.password_hash.value != "correct horse battery staple"
    assert passwordHasher.hashedPasswords == ["correct horse battery staple"]
    assert unitOfWorkFactory.createdUnits[0].committed is True


@pytest.mark.asyncio
async def test_register_rejects_invalid_password_and_duplicate_username() -> None:
    """无效密码和规范化后重复用户名都不能创建第二个用户。"""
    unitOfWorkFactory = FakeUserUnitOfWorkFactory()
    service, _ = createService(unitOfWorkFactory)

    with pytest.raises(InvalidRegistration):
        await service.register(RegisterUserCommand(username="alice", password="short"))

    command = RegisterUserCommand(
        username="Alice",
        password="correct horse battery staple",
    )
    await service.register(command)
    with pytest.raises(UsernameAlreadyExists):
        await service.register(command)

    assert len(unitOfWorkFactory.users) == 1


@pytest.mark.asyncio
async def test_login_returns_token_for_correct_password() -> None:
    """正确用户名密码应签发以稳定用户 ID 为 sub 的令牌。"""
    unitOfWorkFactory = FakeUserUnitOfWorkFactory()
    service, _ = createService(unitOfWorkFactory)
    identity = await service.register(
        RegisterUserCommand(
            username="alice",
            password="correct horse battery staple",
        )
    )

    token = await service.login(
        LoginCommand(
            username="ALICE",
            password="correct horse battery staple",
        )
    )

    assert token.value == f"token:{identity.user_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["alice", "missing-user"])
async def test_login_uses_same_error_for_wrong_or_missing_user(username: str) -> None:
    """错误密码和不存在用户都应返回统一凭证错误并执行哈希验证。"""
    unitOfWorkFactory = FakeUserUnitOfWorkFactory()
    service, passwordHasher = createService(unitOfWorkFactory)
    await service.register(
        RegisterUserCommand(
            username="alice",
            password="correct horse battery staple",
        )
    )

    with pytest.raises(InvalidCredentials, match="用户名或密码错误"):
        await service.login(
            LoginCommand(
                username=username,
                password="another wrong password",
            )
        )

    assert len(passwordHasher.verifications) == 1
    if username == "missing-user":
        assert passwordHasher.verifications[0][1] is None


@pytest.mark.asyncio
async def test_access_token_must_reference_existing_user() -> None:
    """令牌签名有效但 sub 用户不存在时仍不能建立身份。"""
    unitOfWorkFactory = FakeUserUnitOfWorkFactory()
    service, _ = createService(unitOfWorkFactory)

    with pytest.raises(InvalidAccessToken):
        await service.authenticateAccessToken(f"token:{UserId('missing-user')}")

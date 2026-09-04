"""用户注册、登录和访问令牌认证应用服务。"""

from src.application.authModels import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    AccessToken,
    LoginCommand,
    RegisterUserCommand,
    UserIdentity,
)
from src.application.authPorts import (
    AccessTokenProvider,
    PasswordHasher,
    UserUnitOfWorkFactory,
)
from src.application.exceptions import (
    InvalidAccessToken,
    InvalidCredentials,
    InvalidRegistration,
    UsernameAlreadyExists,
)
from src.domain import DomainError, User, Username, createUser


class AuthenticationService:
    """协调用户持久化、密码哈希和访问令牌。"""

    def __init__(
        self,
        userUnitOfWorkFactory: UserUnitOfWorkFactory,
        passwordHasher: PasswordHasher,
        accessTokenProvider: AccessTokenProvider,
    ) -> None:
        """显式接收认证用例依赖的端口。"""
        self._userUnitOfWorkFactory = userUnitOfWorkFactory
        self._passwordHasher = passwordHasher
        self._accessTokenProvider = accessTokenProvider

    async def register(self, command: RegisterUserCommand) -> UserIdentity:
        """验证输入、哈希密码并原子创建用户。"""
        username = self._parseUsername(command.username, InvalidRegistration)
        self._validatePassword(command.password, InvalidRegistration)
        passwordHash = await self._passwordHasher.hashPassword(command.password)
        user = createUser(username=username, passwordHash=passwordHash)

        async with self._userUnitOfWorkFactory() as unitOfWork:
            existingUser = await unitOfWork.users.getByUsername(username)
            if existingUser is not None:
                raise UsernameAlreadyExists("用户名已存在")
            await unitOfWork.users.add(user)
            await unitOfWork.commit()

        return self._toIdentity(user)

    async def login(self, command: LoginCommand) -> AccessToken:
        """使用统一错误验证用户名和密码并签发短期令牌。"""
        username = self._parseUsername(command.username, InvalidCredentials)
        self._validatePassword(command.password, InvalidCredentials)

        async with self._userUnitOfWorkFactory() as unitOfWork:
            user = await unitOfWork.users.getByUsername(username)

        passwordHash = user.password_hash if user is not None else None
        if not await self._passwordHasher.verifyPassword(
            command.password,
            passwordHash,
        ):
            raise InvalidCredentials("用户名或密码错误")
        if user is None:
            raise InvalidCredentials("用户名或密码错误")
        return self._accessTokenProvider.createAccessToken(user.user_id)

    async def authenticateAccessToken(self, token: str) -> UserIdentity:
        """验证令牌声明，并确认 sub 对应用户仍然存在。"""
        userId = self._accessTokenProvider.getUserId(token)
        async with self._userUnitOfWorkFactory() as unitOfWork:
            user = await unitOfWork.users.getById(userId)
        if user is None:
            raise InvalidAccessToken("访问令牌对应用户不存在")
        return self._toIdentity(user)

    def _parseUsername(
        self,
        value: str,
        errorType: type[InvalidRegistration] | type[InvalidCredentials],
    ) -> Username:
        """规范化用户名并转换领域异常。"""
        try:
            return Username(value)
        except DomainError as error:
            raise errorType("用户名格式无效") from error

    def _validatePassword(
        self,
        password: str,
        errorType: type[InvalidRegistration] | type[InvalidCredentials],
    ) -> None:
        """验证密码长度，不施加降低可用性的字符组合规则。"""
        if not isinstance(password, str):
            raise errorType("密码必须是字符串")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise errorType(
                f"密码长度必须在 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 之间"
            )

    def _toIdentity(self, user: User) -> UserIdentity:
        """移除密码哈希，只向外返回身份信息。"""
        return UserIdentity(user_id=user.user_id, username=user.username)

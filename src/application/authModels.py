"""用户注册、登录和访问令牌应用模型。"""

from dataclasses import dataclass
from datetime import datetime

from src.domain import UserId, Username

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    """注册用户命令，明文密码只存在于当前调用范围。"""

    username: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """用户名密码登录命令。"""

    username: str
    password: str


@dataclass(frozen=True, slots=True)
class UserIdentity:
    """不包含密码哈希的可信用户身份。"""

    user_id: UserId
    username: Username


@dataclass(frozen=True, slots=True)
class AccessToken:
    """短期 Bearer 访问令牌及其过期时间。"""

    value: str
    expires_at: datetime
    token_type: str = "bearer"

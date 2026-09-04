"""使用固定 HS256 算法签发和验证短期 JWT。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError

from src.application.authModels import AccessToken
from src.application.authPorts import AccessTokenProvider
from src.application.exceptions import InvalidAccessToken
from src.config import JWT_ALGORITHM
from src.domain import UserId


class JwtAccessTokenProvider(AccessTokenProvider):
    """只接受服务端固定算法的签名 JWT。"""

    def __init__(self, *, secretKey: str, expireMinutes: int) -> None:
        """接收不会写入代码或日志的环境密钥和短期有效期。"""
        self._secretKey = secretKey
        self._expireMinutes = expireMinutes

    def createAccessToken(self, userId: UserId) -> AccessToken:
        """签发只包含身份、签发时间和过期时间的 JWT。"""
        issuedAt = datetime.now(timezone.utc)
        expiresAt = issuedAt + timedelta(minutes=self._expireMinutes)
        token = jwt.encode(
            {
                "sub": str(userId),
                "iat": issuedAt,
                "exp": expiresAt,
            },
            self._secretKey,
            algorithm=JWT_ALGORITHM,
        )
        return AccessToken(value=token, expires_at=expiresAt)

    def getUserId(self, token: str) -> UserId:
        """固定算法白名单并要求 sub、iat、exp 均存在。"""
        try:
            payload = jwt.decode(
                token,
                self._secretKey,
                algorithms=[JWT_ALGORITHM],
                options={"require": ["sub", "iat", "exp"]},
            )
            subject = payload["sub"]
            if not isinstance(subject, str):
                raise InvalidAccessToken("访问令牌 sub 类型无效")
            return UserId(str(UUID(subject)))
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, InvalidAccessToken):
                raise
            raise InvalidAccessToken("访问令牌无效或已过期") from error

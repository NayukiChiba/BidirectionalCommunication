"""用户注册、登录和 HTTP Bearer 身份入口。"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field

from src.application import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    AuthenticationService,
    InvalidAccessToken,
    InvalidCredentials,
    InvalidRegistration,
    LoginCommand,
    RegisterUserCommand,
    UserIdentity,
    UsernameAlreadyExists,
    UserStorageError,
)

logger = logging.getLogger(__name__)

oauth2Scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


class RegisterUserPayload(BaseModel):
    """注册请求，只在当前请求内持有明文密码。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
    )


class UserIdentityResponse(BaseModel):
    """不包含密码或密码哈希的用户身份响应。"""

    user_id: str
    username: str


class AccessTokenResponse(BaseModel):
    """OAuth2 Bearer 访问令牌响应。"""

    access_token: str
    token_type: str
    expires_at: datetime


class CurrentUserDependency:
    """通过 Bearer 令牌解析当前 HTTP 用户。"""

    def __init__(self, authenticationService: AuthenticationService) -> None:
        self._authenticationService = authenticationService

    async def __call__(
        self,
        request: Request,
        token: Annotated[str | None, Depends(oauth2Scheme)],
    ) -> UserIdentity:
        """验证令牌并返回数据库中仍然存在的可信用户。"""
        if token is None:
            self._logRejection(request)
            raise createCredentialsError()
        try:
            return await self._authenticationService.authenticateAccessToken(token)
        except InvalidAccessToken as error:
            self._logRejection(request)
            raise createCredentialsError() from error
        except UserStorageError as error:
            logger.error(
                "http_authentication_storage_failed",
                extra={
                    "event": "authentication_storage_failed",
                    "request_id": request.state.requestId,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="身份存储暂时不可用",
            ) from error

    @staticmethod
    def _logRejection(request: Request) -> None:
        """记录不包含凭证内容的统一认证拒绝事件。"""
        logger.warning(
            "http_authentication_rejected",
            extra={
                "event": "authentication_rejected",
                "request_id": request.state.requestId,
            },
        )


def createCredentialsError() -> HTTPException:
    """创建不泄露具体认证失败原因的统一 401 响应。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证身份凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )


def toIdentityResponse(identity: UserIdentity) -> UserIdentityResponse:
    """把应用身份转换为不含敏感字段的 HTTP 响应。"""
    return UserIdentityResponse(
        user_id=str(identity.user_id),
        username=str(identity.username),
    )


def createAuthenticationRouter(
    authenticationService: AuthenticationService,
    currentUserDependency: CurrentUserDependency,
) -> APIRouter:
    """创建注册、登录和当前用户路由。"""
    router = APIRouter(prefix="/auth", tags=["authentication"])

    @router.post(
        "/register",
        response_model=UserIdentityResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def registerUser(payload: RegisterUserPayload) -> UserIdentityResponse:
        """注册用户，数据库只接收专用库生成的密码哈希。"""
        try:
            identity = await authenticationService.register(
                RegisterUserCommand(
                    username=payload.username,
                    password=payload.password,
                )
            )
        except UsernameAlreadyExists as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="用户名已存在",
            ) from error
        except InvalidRegistration as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except UserStorageError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="用户存储暂时不可用",
            ) from error
        return toIdentityResponse(identity)

    @router.post("/token", response_model=AccessTokenResponse)
    async def loginForAccessToken(
        formData: Annotated[OAuth2PasswordRequestForm, Depends()],
    ) -> AccessTokenResponse:
        """验证用户名密码并签发短期 Bearer 令牌。"""
        try:
            accessToken = await authenticationService.login(
                LoginCommand(username=formData.username, password=formData.password)
            )
        except InvalidCredentials as error:
            raise createCredentialsError() from error
        except UserStorageError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="身份存储暂时不可用",
            ) from error
        return AccessTokenResponse(
            access_token=accessToken.value,
            token_type=accessToken.token_type,
            expires_at=accessToken.expires_at,
        )

    @router.get("/me", response_model=UserIdentityResponse)
    async def getCurrentUser(
        currentUser: Annotated[UserIdentity, Depends(currentUserDependency)],
    ) -> UserIdentityResponse:
        """返回当前 Bearer 令牌对应身份。"""
        return toIdentityResponse(currentUser)

    return router

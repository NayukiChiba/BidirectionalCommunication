"""FastAPI 应用的唯一组合根。"""

import logging
import os
import secrets
import socket
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import uvicorn
from alembic import command
from fastapi import FastAPI
from pydantic import ValidationError

from src.adapters import (
    ConnectionManager,
    WebSocketMessageNotifier,
    WebSocketRateLimiter,
)
from src.adapters.database import (
    AsyncSqlAlchemyConversationUnitOfWorkFactory,
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
    AsyncSqlAlchemyUserUnitOfWorkFactory,
    DatabaseReadinessProbe,
    createAsyncDatabaseEngine,
    createAsyncSessionFactory,
    createAsyncSqliteUrl,
)
from src.adapters.database.migrationConfig import createMigrationConfig
from src.adapters.redis import RedisRealtimeGateway, createRedisClient
from src.adapters.security import JwtAccessTokenProvider, PwdlibPasswordHasher
from src.application import (
    AdvanceConversationPositionService,
    AuthenticationService,
    CreateConversationService,
    GetMessageHistoryService,
    SendMessageService,
    SyncMessagesService,
)
from src.config import (
    DATA_DIR,
    DATABASE_HEAD_REVISION,
    DEFAULT_DATABASE_URL,
    AuthSettings,
    DatabaseSettings,
    RedisSettings,
    RuntimeSettings,
)
from src.entrypoints import (
    CurrentUserDependency,
    addRequestContextMiddleware,
    create_router,
    createAuthenticationRouter,
    createConversationRouter,
    createHealthRouter,
    createHistoryRouter,
)
from src.observability import configureStructuredLogging

logger = logging.getLogger(__name__)

STANDALONE_DATABASE_FILENAME = "chat.sqlite3"
STANDALONE_SECRET_FILENAME = "auth-secret"


def create_app(
    *,
    databasePath: Path | None = None,
    authSettings: AuthSettings | None = None,
    databaseSettings: DatabaseSettings | None = None,
    redisSettings: RedisSettings | None = None,
    runtimeSettings: RuntimeSettings | None = None,
) -> FastAPI:
    """创建并组装可运行的 FastAPI 应用。"""
    resolvedAuthSettings = authSettings or AuthSettings()
    resolvedDatabaseSettings = databaseSettings or DatabaseSettings()
    resolvedRedisSettings = redisSettings or RedisSettings()
    resolvedRuntimeSettings = runtimeSettings or RuntimeSettings()
    configureStructuredLogging(resolvedRuntimeSettings.logLevel)
    connection_manager = ConnectionManager(
        maxConnections=resolvedRuntimeSettings.maxWebSocketConnections
    )
    redis_realtime_gateway: RedisRealtimeGateway | None = None
    connection_gateway = connection_manager
    if resolvedRedisSettings.enabled:
        redisUrl = resolvedRedisSettings.redisUrl
        if redisUrl is None:
            raise RuntimeError("Redis 已启用但缺少 REDIS_URL")
        instanceId = resolvedRedisSettings.instanceId or (
            f"{socket.gethostname()}-{uuid4().hex[:8]}"
        )
        redisClient = createRedisClient(
            redisUrl.get_secret_value(),
            resolvedRedisSettings.maxConnections,
        )
        redis_realtime_gateway = RedisRealtimeGateway(
            connection_manager,
            redisClient,
            instanceId=instanceId,
            channelPrefix=resolvedRedisSettings.channelPrefix,
            presenceLeaseSeconds=resolvedRedisSettings.presenceLeaseSeconds,
            presenceRefreshSeconds=resolvedRedisSettings.presenceRefreshSeconds,
            subscriberRetrySeconds=resolvedRedisSettings.subscriberRetrySeconds,
            operationTimeoutSeconds=resolvedRedisSettings.operationTimeoutSeconds,
            recentEventTtlSeconds=resolvedRedisSettings.recentEventTtlSeconds,
            recentEventLimit=resolvedRedisSettings.recentEventLimit,
        )
        connection_gateway = redis_realtime_gateway
    databaseUrl = (
        createAsyncSqliteUrl(databasePath)
        if databasePath is not None
        else resolvedDatabaseSettings.databaseUrl.get_secret_value()
    )
    database_engine = createAsyncDatabaseEngine(
        databaseUrl,
        poolSize=resolvedDatabaseSettings.poolSize,
        maxOverflow=resolvedDatabaseSettings.maxOverflow,
        poolTimeoutSeconds=resolvedDatabaseSettings.poolTimeoutSeconds,
        poolRecycleSeconds=resolvedDatabaseSettings.poolRecycleSeconds,
    )
    session_factory = createAsyncSessionFactory(database_engine)
    unit_of_work_factory = AsyncSqlAlchemyMessageUnitOfWorkFactory(session_factory)
    conversation_unit_of_work_factory = AsyncSqlAlchemyConversationUnitOfWorkFactory(
        session_factory
    )
    user_unit_of_work_factory = AsyncSqlAlchemyUserUnitOfWorkFactory(session_factory)
    password_hasher = PwdlibPasswordHasher()
    access_token_provider = JwtAccessTokenProvider(
        secretKey=resolvedAuthSettings.secretKey.get_secret_value(),
        expireMinutes=resolvedAuthSettings.accessTokenExpireMinutes,
    )
    authentication_service = AuthenticationService(
        userUnitOfWorkFactory=user_unit_of_work_factory,
        passwordHasher=password_hasher,
        accessTokenProvider=access_token_provider,
    )
    current_user_dependency = CurrentUserDependency(authentication_service)
    message_notifier = WebSocketMessageNotifier(connection_gateway)
    send_message_service = SendMessageService(
        unitOfWorkFactory=unit_of_work_factory,
        conversationUnitOfWorkFactory=conversation_unit_of_work_factory,
        notifier=message_notifier,
    )
    conversation_service = CreateConversationService(
        conversationUnitOfWorkFactory=conversation_unit_of_work_factory,
        userUnitOfWorkFactory=user_unit_of_work_factory,
    )
    history_service = GetMessageHistoryService(
        unit_of_work_factory,
        conversation_unit_of_work_factory,
    )
    position_service = AdvanceConversationPositionService(
        conversation_unit_of_work_factory
    )
    sync_service = SyncMessagesService(position_service, history_service)
    readiness_probe = DatabaseReadinessProbe(
        database_engine,
        expectedRevision=DATABASE_HEAD_REVISION,
        timeoutSeconds=resolvedRuntimeSettings.readinessTimeoutSeconds,
    )
    rate_limiter_factory = partial(
        WebSocketRateLimiter,
        limit=resolvedRuntimeSettings.inputRateLimitCount,
        windowSeconds=resolvedRuntimeSettings.inputRateLimitWindowSeconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """释放组合根创建的连接资源。"""
        try:
            if redis_realtime_gateway is not None:
                await redis_realtime_gateway.start()
            logger.info("application_started", extra={"event": "lifecycle"})
            yield
        finally:
            logger.info("application_stopping", extra={"event": "lifecycle"})
            connection_manager.stopAccepting()
            if redis_realtime_gateway is not None:
                await redis_realtime_gateway.close()
            await connection_manager.close_all()
            await database_engine.dispose()
            logger.info("application_stopped", extra={"event": "lifecycle"})

    app = FastAPI(lifespan=lifespan)
    addRequestContextMiddleware(app)
    app.state.connection_manager = connection_manager
    app.state.database_engine = database_engine
    app.state.database_settings = resolvedDatabaseSettings
    app.state.redis_settings = resolvedRedisSettings
    app.state.realtime_gateway = connection_gateway
    app.state.session_factory = session_factory
    app.state.unit_of_work_factory = unit_of_work_factory
    app.state.user_unit_of_work_factory = user_unit_of_work_factory
    app.state.conversation_unit_of_work_factory = conversation_unit_of_work_factory
    app.state.message_notifier = message_notifier
    app.state.send_message_service = send_message_service
    app.state.history_service = history_service
    app.state.authentication_service = authentication_service
    app.state.conversation_service = conversation_service
    app.state.position_service = position_service
    app.state.sync_service = sync_service
    app.state.readiness_probe = readiness_probe
    app.state.runtime_settings = resolvedRuntimeSettings
    app.include_router(createHealthRouter(readiness_probe))
    app.include_router(
        createAuthenticationRouter(
            authentication_service,
            current_user_dependency,
        )
    )
    app.include_router(
        createConversationRouter(
            conversation_service,
            current_user_dependency,
        )
    )
    app.include_router(
        create_router(
            send_message_service=send_message_service,
            connection_gateway=connection_gateway,
            authenticationService=authentication_service,
            positionService=position_service,
            syncService=sync_service,
            rateLimiterFactory=rate_limiter_factory,
            maxMessageBytes=resolvedRuntimeSettings.maxWebSocketMessageBytes,
        )
    )
    app.include_router(
        createHistoryRouter(
            history_service,
            current_user_dependency,
        )
    )
    return app


def createStandaloneApp(
    *,
    dataDirectory: Path | None = None,
    forceLocalServices: bool = False,
) -> FastAPI:
    """创建自动准备数据库和认证密钥的单机应用。"""
    resolvedDataDirectory = (dataDirectory or DATA_DIR).expanduser().resolve()
    resolvedDataDirectory.mkdir(parents=True, exist_ok=True)
    authSettings = _createStandaloneAuthSettings(
        resolvedDataDirectory,
        forceLocalServices=forceLocalServices,
    )
    databaseSettings = (
        DatabaseSettings(databaseUrl=DEFAULT_DATABASE_URL, _env_file=None)
        if forceLocalServices
        else DatabaseSettings()
    )
    configuredDatabaseUrl = databaseSettings.databaseUrl.get_secret_value()
    useLocalSqlite = forceLocalServices or configuredDatabaseUrl == DEFAULT_DATABASE_URL
    databaseTarget: Path | str = (
        resolvedDataDirectory / STANDALONE_DATABASE_FILENAME
        if useLocalSqlite
        else configuredDatabaseUrl
    )
    command.upgrade(createMigrationConfig(databaseTarget), "head")
    return create_app(
        databasePath=databaseTarget if isinstance(databaseTarget, Path) else None,
        authSettings=authSettings,
        databaseSettings=databaseSettings,
        redisSettings=(
            RedisSettings(redisUrl=None, _env_file=None)
            if forceLocalServices
            else RedisSettings()
        ),
    )


def runStandaloneApp(
    app: FastAPI,
    *,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """直接运行已经完成本地准备的单机应用。"""
    resolvedHost = host or os.getenv("APP_HOST", "127.0.0.1")
    resolvedPort = port or int(os.getenv("APP_PORT", "8000"))
    if not 1 <= resolvedPort <= 65_535:
        raise ValueError("APP_PORT 必须在 1 到 65535 之间")
    uvicorn.run(app, host=resolvedHost, port=resolvedPort, ws_max_size=16_384)


def _createStandaloneAuthSettings(
    dataDirectory: Path,
    *,
    forceLocalServices: bool,
) -> AuthSettings:
    """优先读取显式配置，否则创建单机专用随机密钥。"""
    if not forceLocalServices:
        try:
            return AuthSettings()
        except ValidationError as error:
            errors = error.errors()
            isOnlyMissingSecret = len(errors) == 1 and errors[0]["type"] == "missing"
            if not isOnlyMissingSecret:
                raise
    secretPath = dataDirectory / STANDALONE_SECRET_FILENAME
    secretValue = _loadOrCreateSecret(secretPath)
    return AuthSettings(secretKey=secretValue, _env_file=None)


def _loadOrCreateSecret(secretPath: Path) -> str:
    """并发安全地读取或创建本机认证密钥。"""
    if secretPath.exists():
        return secretPath.read_text(encoding="utf-8").strip()
    generatedSecret = secrets.token_hex(32)
    try:
        with secretPath.open("x", encoding="utf-8") as secretFile:
            secretFile.write(generatedSecret)
        if os.name != "nt":
            secretPath.chmod(0o600)
        return generatedSecret
    except FileExistsError:
        return secretPath.read_text(encoding="utf-8").strip()

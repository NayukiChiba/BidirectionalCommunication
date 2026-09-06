"""FastAPI 应用的唯一组合根。"""

import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

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
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
)
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
    DATABASE_HEAD_REVISION,
    DATABASE_PATH,
    AuthSettings,
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


def create_app(
    *,
    databasePath: Path = DATABASE_PATH,
    authSettings: AuthSettings | None = None,
    runtimeSettings: RuntimeSettings | None = None,
) -> FastAPI:
    """创建并组装可运行的 FastAPI 应用。"""
    resolvedAuthSettings = authSettings or AuthSettings()
    resolvedRuntimeSettings = runtimeSettings or RuntimeSettings()
    configureStructuredLogging(resolvedRuntimeSettings.logLevel)
    connection_manager = ConnectionManager(
        maxConnections=resolvedRuntimeSettings.maxWebSocketConnections
    )
    database_engine = createAsyncSqliteEngine(databasePath)
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
    message_notifier = WebSocketMessageNotifier(connection_manager)
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
            logger.info("application_started", extra={"event": "lifecycle"})
            yield
        finally:
            logger.info("application_stopping", extra={"event": "lifecycle"})
            connection_manager.stopAccepting()
            await connection_manager.close_all()
            await database_engine.dispose()
            logger.info("application_stopped", extra={"event": "lifecycle"})

    app = FastAPI(lifespan=lifespan)
    addRequestContextMiddleware(app)
    app.state.connection_manager = connection_manager
    app.state.database_engine = database_engine
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
            connection_gateway=connection_manager,
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

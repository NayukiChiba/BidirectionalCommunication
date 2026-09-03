"""FastAPI 应用的唯一组合根。"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from src.adapters import (
    ConnectionManager,
    WebSocketMessageNotifier,
)
from src.adapters.database import (
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
)
from src.application import GetMessageHistoryService, SendMessageService
from src.config import DATABASE_PATH
from src.entrypoints import create_router, createHistoryRouter


def create_app(*, databasePath: Path = DATABASE_PATH) -> FastAPI:
    """创建并组装可运行的 FastAPI 应用。"""
    connection_manager = ConnectionManager()
    database_engine = createAsyncSqliteEngine(databasePath)
    session_factory = createAsyncSessionFactory(database_engine)
    unit_of_work_factory = AsyncSqlAlchemyMessageUnitOfWorkFactory(session_factory)
    message_notifier = WebSocketMessageNotifier(connection_manager)
    send_message_service = SendMessageService(
        unitOfWorkFactory=unit_of_work_factory,
        notifier=message_notifier,
    )
    history_service = GetMessageHistoryService(unit_of_work_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """释放组合根创建的连接资源。"""
        try:
            yield
        finally:
            await connection_manager.close_all()
            await database_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.connection_manager = connection_manager
    app.state.database_engine = database_engine
    app.state.session_factory = session_factory
    app.state.unit_of_work_factory = unit_of_work_factory
    app.state.message_notifier = message_notifier
    app.state.send_message_service = send_message_service
    app.state.history_service = history_service
    app.include_router(
        create_router(
            send_message_service=send_message_service,
            connection_gateway=connection_manager,
        )
    )
    app.include_router(createHistoryRouter(history_service))
    return app

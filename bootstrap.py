"""FastAPI 应用的唯一组合根。"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.adapters import (
    ConnectionManager,
    InMemoryMessageRepository,
    WebSocketMessageNotifier,
)
from src.application import SendMessageService
from src.entrypoints import create_router


def create_app() -> FastAPI:
    """创建并组装可运行的 FastAPI 应用。"""
    connection_manager = ConnectionManager()
    message_repository = InMemoryMessageRepository()
    message_notifier = WebSocketMessageNotifier(connection_manager)
    send_message_service = SendMessageService(
        repository=message_repository,
        notifier=message_notifier,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """释放组合根创建的连接资源。"""
        try:
            yield
        finally:
            await connection_manager.close_all()

    app = FastAPI(lifespan=lifespan)
    app.state.connection_manager = connection_manager
    app.state.message_repository = message_repository
    app.state.message_notifier = message_notifier
    app.state.send_message_service = send_message_service
    app.include_router(
        create_router(
            send_message_service=send_message_service,
            connection_gateway=connection_manager,
        )
    )
    return app

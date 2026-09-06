"""外部技术能力的适配器。"""

from src.adapters.inMemoryMessageRepository import InMemoryMessageRepository
from src.adapters.inMemoryMessageUnitOfWork import (
    InMemoryMessageUnitOfWork,
    InMemoryMessageUnitOfWorkFactory,
)
from src.adapters.webSocketConnectionManager import (
    CONNECTION_LIMIT_CODE,
    CONNECTION_LIMIT_REASON,
    DUPLICATE_CONNECTION_CODE,
    DUPLICATE_CONNECTION_REASON,
    SERVICE_NOT_ACCEPTING_CODE,
    SERVICE_NOT_ACCEPTING_REASON,
    SERVICE_SHUTDOWN_CODE,
    SERVICE_SHUTDOWN_REASON,
    ConnectionManager,
    ConnectionSendOutcome,
)
from src.adapters.webSocketMessageNotifier import (
    WebSocketMessageNotifier,
)
from src.adapters.webSocketRateLimiter import WebSocketRateLimiter

__all__ = [
    "ConnectionSendOutcome",
    "ConnectionManager",
    "CONNECTION_LIMIT_CODE",
    "CONNECTION_LIMIT_REASON",
    "DUPLICATE_CONNECTION_CODE",
    "DUPLICATE_CONNECTION_REASON",
    "InMemoryMessageRepository",
    "InMemoryMessageUnitOfWork",
    "InMemoryMessageUnitOfWorkFactory",
    "SERVICE_SHUTDOWN_CODE",
    "SERVICE_SHUTDOWN_REASON",
    "SERVICE_NOT_ACCEPTING_CODE",
    "SERVICE_NOT_ACCEPTING_REASON",
    "WebSocketMessageNotifier",
    "WebSocketRateLimiter",
]

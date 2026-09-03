"""外部技术能力的适配器。"""

from src.adapters.inMemoryMessageRepository import InMemoryMessageRepository
from src.adapters.inMemoryMessageUnitOfWork import (
    InMemoryMessageUnitOfWork,
    InMemoryMessageUnitOfWorkFactory,
)
from src.adapters.webSocketConnectionManager import (
    DUPLICATE_CONNECTION_CODE,
    DUPLICATE_CONNECTION_REASON,
    SERVICE_SHUTDOWN_CODE,
    SERVICE_SHUTDOWN_REASON,
    ConnectionManager,
    ConnectionSendOutcome,
)
from src.adapters.webSocketMessageNotifier import (
    WebSocketMessageNotifier,
)

__all__ = [
    "ConnectionSendOutcome",
    "ConnectionManager",
    "DUPLICATE_CONNECTION_CODE",
    "DUPLICATE_CONNECTION_REASON",
    "InMemoryMessageRepository",
    "InMemoryMessageUnitOfWork",
    "InMemoryMessageUnitOfWorkFactory",
    "SERVICE_SHUTDOWN_CODE",
    "SERVICE_SHUTDOWN_REASON",
    "WebSocketMessageNotifier",
]

"""外部技术能力的适配器。"""

from adapters.inMemoryMessageRepository import InMemoryMessageRepository
from adapters.webSocketConnectionManager import (
    DUPLICATE_CONNECTION_CODE,
    DUPLICATE_CONNECTION_REASON,
    SERVICE_SHUTDOWN_CODE,
    SERVICE_SHUTDOWN_REASON,
    ConnectionManager,
    ConnectionSendOutcome,
)
from adapters.webSocketMessageNotifier import (
    WebSocketMessageNotifier,
)

__all__ = [
    "ConnectionSendOutcome",
    "ConnectionManager",
    "DUPLICATE_CONNECTION_CODE",
    "DUPLICATE_CONNECTION_REASON",
    "InMemoryMessageRepository",
    "SERVICE_SHUTDOWN_CODE",
    "SERVICE_SHUTDOWN_REASON",
    "WebSocketMessageNotifier",
]

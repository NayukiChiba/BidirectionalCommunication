"""应用层公开接口。"""

from src.application.exceptions import (
    InvalidMessageHistoryQuery,
    MessageStorageConflictError,
    MessageStorageError,
)
from src.application.getMessageHistory import GetMessageHistoryService
from src.application.models import (
    DEFAULT_HISTORY_PAGE_SIZE,
    MAX_HISTORY_PAGE_SIZE,
    DeliveryOutcome,
    MessageCursor,
    MessageHistoryPage,
    MessageHistoryQuery,
    SendMessageCommand,
    SendMessageResult,
    SendMessageStatus,
)
from src.application.ports import (
    MessageNotifier,
    MessageRepository,
    MessageUnitOfWork,
    MessageUnitOfWorkFactory,
)
from src.application.sendMessage import SendMessageService

__all__ = [
    "DEFAULT_HISTORY_PAGE_SIZE",
    "DeliveryOutcome",
    "GetMessageHistoryService",
    "InvalidMessageHistoryQuery",
    "MAX_HISTORY_PAGE_SIZE",
    "MessageCursor",
    "MessageHistoryPage",
    "MessageHistoryQuery",
    "MessageNotifier",
    "MessageRepository",
    "MessageStorageError",
    "MessageStorageConflictError",
    "MessageUnitOfWork",
    "MessageUnitOfWorkFactory",
    "SendMessageCommand",
    "SendMessageResult",
    "SendMessageService",
    "SendMessageStatus",
]

"""发送消息应用用例的输入与结果。"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from domain import ChatMessage


@dataclass(frozen=True, slots=True)
class SendMessageCommand:
    """与具体传输协议无关的发送消息命令。"""

    sender_id: str
    recipient_id: str
    content: str
    client_message_id: UUID


class DeliveryOutcome(StrEnum):
    """实时通知端口能够返回的投递结果。"""

    DELIVERED = "delivered"
    RECIPIENT_OFFLINE = "recipient_offline"
    FAILED = "failed"


class SendMessageStatus(StrEnum):
    """发送消息用例的最终结果。"""

    DELIVERED = "delivered"
    RECIPIENT_OFFLINE = "recipient_offline"
    DELIVERY_FAILED = "delivery_failed"
    STORAGE_FAILED = "storage_failed"
    INVALID_MESSAGE = "invalid_message"


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    """供入口层转换为具体协议响应的应用结果。"""

    status: SendMessageStatus
    message: ChatMessage | None = None

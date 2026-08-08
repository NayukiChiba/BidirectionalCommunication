"""应用用例依赖的端口。"""

from typing import Protocol

from application.models import DeliveryOutcome
from domain import ChatMessage


class MessageRepository(Protocol):
    """发送消息用例需要的最小消息存储端口。"""

    def add(self, message: ChatMessage) -> None:
        """保存一条已经创建的聊天消息。"""
        ...


class MessageNotifier(Protocol):
    """发送消息用例需要的最小实时通知端口。"""

    async def deliver(self, message: ChatMessage) -> DeliveryOutcome:
        """尝试将消息实时投递给接收者。"""
        ...

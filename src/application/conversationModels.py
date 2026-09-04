"""一对一会话应用用例的输入与结果。"""

from dataclasses import dataclass

from src.domain import Conversation


@dataclass(frozen=True, slots=True)
class CreateConversationCommand:
    """创建或获取一对一会话的命令。"""

    current_user_id: str
    peer_id: str


@dataclass(frozen=True, slots=True)
class CreateConversationResult:
    """返回稳定会话身份及本次是否实际创建。"""

    conversation: Conversation
    created: bool

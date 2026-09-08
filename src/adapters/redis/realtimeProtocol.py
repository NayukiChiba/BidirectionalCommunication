"""Redis Pub/Sub 使用的最小版本化内部实时事件协议。"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

INTERNAL_PROTOCOL_VERSION = 1


class RealtimeMessagePayload(BaseModel):
    """与客户端 message 事件字段一致的受限内部载荷。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message"]
    server_message_id: UUID
    client_message_id: UUID
    conversation_id: UUID
    sender_id: str = Field(min_length=1, max_length=64)
    recipient_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=2_000)
    sent_at: datetime


class RealtimeDeliveryEvent(BaseModel):
    """从源实例路由到目标实例的幂等内部事件。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = INTERNAL_PROTOCOL_VERSION
    event_type: Literal["message.deliver"] = "message.deliver"
    event_id: UUID = Field(default_factory=uuid4)
    source_instance_id: str = Field(min_length=1, max_length=128)
    target_user_id: str = Field(min_length=1, max_length=64)
    payload: RealtimeMessagePayload

    def toJson(self) -> str:
        """序列化为 Redis 频道使用的紧凑 JSON。"""
        return self.model_dump_json()

    @classmethod
    def fromJson(cls, value: str | bytes) -> "RealtimeDeliveryEvent":
        """解析并验证不可信的频道消息。"""
        return cls.model_validate_json(value)

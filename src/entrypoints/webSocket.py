"""FastAPI WebSocket 输入入口。"""

from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..application import (
    SendMessageCommand,
    SendMessageService,
    SendMessageStatus,
)


class WebSocketConnectionGateway(Protocol):
    """WebSocket 入口需要的最小连接管理能力。"""

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """接受并登记用户连接。"""
        ...

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """删除仍属于用户的指定连接。"""
        ...

    async def send_message_to_user(
        self,
        sender_id: str | None = None,
        *,
        user_id: str | None = None,
        data: dict[str, object],
    ) -> bool:
        """向用户当前连接发送协议数据。"""
        ...


class SendMessagePayload(BaseModel):
    """客户端发送消息的 WebSocket 载荷。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["send_message"]
    recipient_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=2000)
    client_message_id: UUID

    @field_validator("recipient_id")
    @classmethod
    def validate_recipient_id(cls, recipient_id: str) -> str:
        """规范化并拒绝空白接收者标识。"""
        normalized_recipient_id = recipient_id.strip()
        if not normalized_recipient_id:
            raise ValueError("接收者的 ID 不能为空")
        return normalized_recipient_id

    @field_validator("content")
    @classmethod
    def validate_content(cls, content: str) -> str:
        """规范化并拒绝空白消息内容。"""
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("发送消息不能为空")
        return normalized_content


class ErrorEvent(BaseModel):
    """服务端 WebSocket 错误事件。"""

    type: Literal["error"] = "error"
    code: str
    message: str
    client_message_id: UUID | None = None


def create_router(
    *,
    send_message_service: SendMessageService,
    connection_gateway: WebSocketConnectionGateway,
) -> APIRouter:
    """创建已经注入应用服务和连接网关的 FastAPI 路由。"""
    router = APIRouter()

    @router.get("/health")
    async def get_health() -> dict[str, str]:
        """返回服务健康状态。"""
        return {"status": "ok"}

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, user_id: str) -> None:
        """接收发送消息命令，并将应用结果映射为 WebSocket 协议响应。"""
        await connection_gateway.connect(user_id=user_id, websocket=websocket)

        try:
            while True:
                raw_message = await websocket.receive_text()
                client_message_id: UUID | None = None
                try:
                    payload = SendMessagePayload.model_validate_json(raw_message)
                    client_message_id = payload.client_message_id
                except ValidationError as validation_error:
                    first_error = validation_error.errors()[0]
                    if first_error["type"] == "json_invalid":
                        error_code = "invalid_json"
                        error_message = "消息不是合法json类型"
                    else:
                        error_code = "invalid_message"
                        error_message = "消息字段验证失败"

                    error_event = ErrorEvent(
                        code=error_code,
                        message=error_message,
                        client_message_id=client_message_id,
                    )
                    await connection_gateway.send_message_to_user(
                        sender_id=user_id,
                        data=error_event.model_dump(mode="json"),
                    )
                    continue

                command = SendMessageCommand(
                    sender_id=user_id,
                    recipient_id=payload.recipient_id,
                    content=payload.content,
                    client_message_id=payload.client_message_id,
                )
                result = await send_message_service.send(command)

                if result.status is SendMessageStatus.DELIVERED:
                    if result.message is None:
                        raise RuntimeError("发送成功结果缺少消息实体")
                    ack = {
                        "type": "ack",
                        "client_message_id": str(result.message.client_message_id),
                        "server_message_id": str(result.message.message_id),
                    }
                    await connection_gateway.send_message_to_user(
                        sender_id=user_id,
                        data=ack,
                    )
                    continue

                error_by_status = {
                    SendMessageStatus.RECIPIENT_OFFLINE: (
                        "recipient_offline",
                        f"用户 {payload.recipient_id} 不在线",
                    ),
                    SendMessageStatus.DELIVERY_FAILED: (
                        "delivery_failed",
                        "消息实时推送失败",
                    ),
                    SendMessageStatus.STORAGE_FAILED: (
                        "message_storage_failed",
                        "消息保存失败",
                    ),
                    SendMessageStatus.INVALID_MESSAGE: (
                        "invalid_message",
                        "消息字段验证失败",
                    ),
                }
                error_code, error_message = error_by_status[result.status]
                error_event = ErrorEvent(
                    code=error_code,
                    message=error_message,
                    client_message_id=payload.client_message_id,
                )
                await connection_gateway.send_message_to_user(
                    sender_id=user_id,
                    data=error_event.model_dump(mode="json"),
                )
        except WebSocketDisconnect:
            connection_gateway.disconnect(user_id=user_id, websocket=websocket)
        finally:
            connection_gateway.disconnect(user_id=user_id, websocket=websocket)

    return router

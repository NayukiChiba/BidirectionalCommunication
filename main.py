"""
FastAPI 应用入口

功能:
1. 创建 FastAPI 应用
2. 提供健康监控检查接口

"""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

app = FastAPI()


class SendMessageCommand(BaseModel):
    """
    BaseModel 是一个带有“自动校验、自动类型转换、自动序列化”功能的 Python 类基类。
    注意不用dataclass，因为BaseModel是一个更加高级的dataclass，自带构造函数
    Attributes:
        type(Literal["send_message"]): 发送消息的类型，代表发送消息，如果是其他类型就报错
        recipient_id(str): 收消息人的id
        content(str): 消息字符串
        client_message_id(UUID): 通信唯一标识

    """

    # model_config(ConfigDict): **注意**这是一个类属性，不是实例属性
    model_config = ConfigDict(
        extra="forbid"
    )  # extra:Literal["ignore", "allow", "forbid"]
    type: Literal["send_message"]  # 命令的类型
    recipient_id: str = Field(min_length=1, max_length=64)  # 收消息人的id
    content: str = Field(min_length=1, max_length=2000)  # 消息字符串
    client_message_id: UUID  # 通信唯一标识

    @field_validator("recipient_id")
    @classmethod
    def validate_recipient_id(cls, recipient_id: str) -> str:
        """
        校验接受者的id
        Args:
            recipient_id(str): 接收者的 ID
        Returns:
            normalized_recipient_id(str): 规范后的接收者的 id
        """

        normalized_recipient_id = recipient_id.strip()

        if not normalized_recipient_id:
            raise ValueError("接收者的 ID 不能为空")
        return normalized_recipient_id

    @field_validator("content")
    @classmethod
    def validate_content(cls, content: str) -> str:
        """
        验证消息内容
        Args:
            content(str): 发送的消息

        Returns:
            normalized_content(str): 规范化后的消息内容
        """
        normalized_content = content.strip()

        if not normalized_content:
            raise ValueError("发送消息不能为空")

        return normalized_content


class MessageEvent(BaseModel):
    """
    服务端消息事件
    Attributes:
        type(Literal["message"]): 消息内容, 固定为message
        server_message_id(UUID): 服务端消息的唯一标识
        client_message_id(UUID): 客户端消息的唯一标识
        sender_id(str): 发送方的 ID
        recipient_id(str): 接收方的 ID
        content(str): 消息内容
        sent_at(datetime): 服务端推送给接收者的时间
    Warnings:
        时间分为三个时间: 发送者点击发送的时间, 服务端收齐全量消息的时间, 服务端推送给接收者的时间
        我们只记录第三个时间
        1. 发送者点击发送的时间我们不知道，因为是客户端决定的
        2. 服务端收齐全量消息的时间，这个是在Server端的业务层的，不归 WebSocket 管， 他会直接记录在数据库(created_at字段)中
        3. 服务端推送给接收者的时间， 这个是我们的 WebSocket 网关负责的
    """

    type: Literal["message"] = "message"
    server_message_id: UUID
    client_message_id: UUID
    sender_id: str
    recipient_id: str
    content: str
    sent_at: datetime


class ErrorEvent(BaseModel):
    """
    服务端错误事件
    Attributes:
        type(Literal["error"]): 错误事件类型
        code(str): 错误码
        message(str): 错误对应的消息
        client_message_id(UUID | None): 客户端消息 id
    """

    type: Literal["error"] = "error"
    code: str
    message: str
    clientMessageId: UUID | None = None


@app.get("/health")
async def get_health():
    """
    :return: 返回服务健康状态
    """
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str) -> None:
    """
    接受客户端的文本并且原样返回
    Args:
        websocket(WebSocket): websocket连接
        user_id(str): 用户的 id, 就是 sender_id 发送方
    Returns:
        None
    """
    # 接受 WebSocket 握手
    await websocket.accept()

    try:
        while True:
            # 等待 websocket 接受文本
            raw_message = (
                await websocket.receive_text()
            )  # 这里一定要 await, 因为要等待接受 receive_text, 是一个异步
            # 先验证一下 raw_message 是不是合法的
            try:
                send_message_command = SendMessageCommand.model_validate_json(
                    raw_message
                )
            except ValidationError as validation_error:
                first_error = validation_error.errors()[
                    0
                ]  # 这是一个List[Dict]类型的错误
                error_type = first_error["type"]

                if error_type == "json_invalid":
                    error_code = "invalid_json"
                    error_message = "消息不是合法json类型"
                else:
                    error_code = "invalid_message"
                    error_message = "消息字段验证失败"
                error_event = ErrorEvent(code=error_code, message=error_message)

                await websocket.send_json(error_event.model_dump(mode="json"))
                continue
            message_event = MessageEvent(
                server_message_id=uuid4(),
                client_message_id=send_message_command.client_message_id,
                sender_id=user_id,
                recipient_id=send_message_command.recipient_id,
                content=send_message_command.content,
                sent_at=datetime.now(timezone.utc),
            )

            await websocket.send_json(message_event.model_dump(mode="json"))

    except WebSocketDisconnect as disconnectError:
        # 客户端断开, 结束当前的连接
        print(f"WebSocket 客户端已断开, 关闭码: {disconnectError.code}")
    finally:
        pass

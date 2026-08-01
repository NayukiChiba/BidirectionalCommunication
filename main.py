"""
FastAPI 应用入口

功能:
1. 创建 FastAPI 应用
2. 提供健康监控检查接口

"""

import warnings
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
    client_message_id: UUID | None = None


class ConnectionManager:
    """
    单进程 WebSocket 在线连接管理器

    职责：
    1. 保存用户 ID 与 WebSocket 的对应关系
    2. 管理用户上线和下线
    3. 判断用户是否在线
    4. 向指定在线用户发送 JSON 数据

    注意：
        该对象只管理当前进程中的技术连接，不负责创建消息、
        验证协议、保存聊天记录或处理用户认证。
    """

    def __init__(self) -> None:
        """初始化在线连接表"""
        # 使用实例变量保存用户 ID 与 WebSocket 的对应关系。
        # 键是用户 ID，值是该用户当前有效的 WebSocket。
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """
        接受 WebSocket 连接并将用户标记为在线
        Args:
            user_id(str): 用户的 id, 也就是发送方的 id
            websocket(WebSocket): websocket 连接
        """
        # 检查 user_id 是否为空
        user_id = user_id.strip()
        if not user_id:
            raise ValueError("user_id 不可以为空")

        # websocket 握手
        await websocket.accept()

        # 保存 user_id 和 websocket 到连接表中
        self._connections[user_id] = websocket

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """
        删除用户的指定 WebSocket 连接

        Args:
            user_id(str): 用户的 id, 也是发送方的 id
            websocket(WebSocket): websocket 连接
        Returns:
            bool: 是否成功删除连接
        """
        # 检查 user_id 是否在当前的连接表中
        if not self.is_online(user_id=user_id):
            return False
        #  检查 websocket 连接是否正确
        if self._connections[user_id] is not websocket:
            return False

        # 如果 user_id 和 websocket 都存在且正确, 就把连接表中的这个内容删除掉
        self._connections.pop(user_id)
        return True

    def is_online(self, user_id: str) -> bool:
        """
        判断用户是否在线, 检查 user_id 是否存在于连接表中, 并返回布尔值。
        Args:
            user_id(str): 用户的 id
        """
        return True if user_id in self._connections else False

    async def send_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> bool:
        """
        旧接口, 已废弃
        向指定在线用户发送 JSON 数据
        Args:
            user_id(str): 用户的 id
            data(dict[str, object]): json数据
        """
        warnings.warn(
            (
                "send_to_user() 已弃用，请改用 "
                "send_message_to_user(sender_id=..., data=...)"
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.send_message_to_user(
            sender_id=user_id,
            data=data,
        )

    async def send_message_to_user(
        self,
        sender_id: str | None = None,
        *,
        user_id: str | None = None,
        data: dict[str, object],
    ) -> bool:
        """
        向指定在线用户发送 JSON 数据

        Args:
            sender_id (str | None): 新版用户 ID 参数
            user_id (str | None): 旧版用户 ID 参数，仅用于兼容
            data (dict[str, object]): JSON 数据

        Returns:
            bool: 是否发送成功

        Raises:
            TypeError: 未提供用户 ID，或者同时提供两个 ID 参数
        """
        if sender_id is not None and user_id is not None:
            raise TypeError("sender_id 和 user_id 不能同时提供")

        if user_id is not None:
            warnings.warn(
                "user_id 参数已弃用，请改用 sender_id",
                DeprecationWarning,
                stacklevel=2,
            )
            sender_id = user_id

        if sender_id is None:
            raise TypeError("缺少必需参数：sender_id")

        # 用户离线时返回 False
        if not self.is_online(user_id=sender_id):
            return False
        # 根据 user_id 查找 WebSocket
        websocket = self._connections[sender_id]
        # 用户在线时等待 send_json(data)
        await websocket.send_json(data)
        return True


@app.get("/health")
async def get_health():
    """
    :return: 返回服务健康状态
    """
    return {"status": "ok"}


# 将局部 ConnectionManager 提升为模块级单例，使不同连接的用户可以互相发现和通信。
manager = ConnectionManager()


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
    await manager.connect(user_id=user_id, websocket=websocket)

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
                client_message_id = send_message_command.client_message_id
            except ValidationError as validation_error:
                first_error = validation_error.errors()[
                    0
                ]  # 这是一个List[Dict]类型的错误
                error_type = first_error["type"]

                if error_type == "json_invalid":
                    error_code = "invalid_json"
                    error_message = "消息不是合法json类型"
                elif error_type == "recipient_offline":
                    error_code = "recipient_offline"
                    error_message = "接收方是离线状态"
                else:
                    error_code = "invalid_message"
                    error_message = "消息字段验证失败"

                error_event = ErrorEvent(
                    code=error_code,
                    message=error_message,
                    client_message_id=client_message_id,
                )

                # 通过 manager.send_message_to_user 向当前用户发送错误事件，
                await manager.send_message_to_user(
                    sender_id=user_id, data=error_event.model_dump(mode="json")
                )
                continue
            # 若 recipient_id == user_id，按既定规则处理，不能靠巧合。
            if not manager.is_online(user_id=send_message_command.recipient_id):
                offline_error = ErrorEvent(
                    code="recipient_offline",
                    message=f"用户{send_message_command.recipient_id} 不在线",
                    client_message_id=send_message_command.client_message_id,
                )
                await manager.send_message_to_user(
                    sender_id=user_id, data=offline_error.model_dump(mode="json")
                )
                continue

            message_event = MessageEvent(
                server_message_id=uuid4(),
                client_message_id=send_message_command.client_message_id,
                sender_id=user_id,
                recipient_id=send_message_command.recipient_id,
                content=send_message_command.content,
                sent_at=datetime.now(timezone.utc),
            )

            # 发送成功后给 sender 返回 ack 确认。
            if not await manager.send_message_to_user(
                sender_id=send_message_command.recipient_id,
                data=message_event.model_dump(mode="json"),
            ):
                offline_error = ErrorEvent(
                    code="recipient_offline",
                    message=f"用户 {send_message_command.recipient_id} 当前离线",
                    client_message_id=send_message_command.client_message_id,
                )
                await manager.send_message_to_user(
                    sender_id=user_id, data=offline_error.model_dump(mode="json")
                )
                continue

            ack = {
                "type": "ack",
                "client_message_id": str(send_message_command.client_message_id),
                "server_message_id": str(message_event.server_message_id),
            }
            await manager.send_message_to_user(sender_id=user_id, data=ack)

    except WebSocketDisconnect:
        # 客户端断开, 结束当前的连接
        manager.disconnect(user_id=user_id, websocket=websocket)
    finally:
        # 接入管理器后，无论正常断开还是发生异常，都调用 disconnect。
        # disconnect 必须只删除与当前 websocket 相同的连接。
        manager.disconnect(user_id=user_id, websocket=websocket)

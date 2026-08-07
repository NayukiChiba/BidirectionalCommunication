"""
FastAPI 应用入口

功能:
1. 创建 FastAPI 应用
2. 提供健康监控检查接口

"""

import logging
import warnings
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from domain import (
    ChatMessage,
    ClientMessageId,
    DomainError,
    MessageContent,
    UserId,
    create_chat_message,
)

logger = logging.getLogger(__name__)

DUPLICATE_CONNECTION_CODE = 4001
DUPLICATE_CONNECTION_REASON = "该账号已在其他连接登录"
SERVICE_SHUTDOWN_CODE = 1001
SERVICE_SHUTDOWN_REASON = "服务停止"


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


def to_chat_message(
    command: SendMessageCommand,
    *,
    sender_id: str,
    recipient_id: str,
) -> ChatMessage:
    """将已校验的传输命令显式转换为消息领域实体。"""
    return create_chat_message(
        client_message_id=ClientMessageId(command.client_message_id),
        sender_id=UserId(sender_id),
        recipient_id=UserId(recipient_id),
        content=MessageContent(command.content),
    )


def to_message_event(message: ChatMessage) -> MessageEvent:
    """将消息领域实体显式转换为 WebSocket 传输事件。"""
    return MessageEvent(
        server_message_id=message.message_id.value,
        client_message_id=message.client_message_id.value,
        sender_id=message.sender_id.value,
        recipient_id=message.recipient_id.value,
        content=message.content.value,
        sent_at=message.created_at,
    )


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

    状态转换：
        未连接 -> 已连接 -> 被新连接替换 -> 关闭
        每个用户最多保留一个当前连接。旧连接退出时只能清理自身，
        不能删除已经替换它的新连接。
    """

    def __init__(self) -> None:
        """初始化在线连接表"""
        # 使用实例变量保存用户 ID 与 WebSocket 的对应关系。
        # 键是用户 ID，值是该用户当前有效的 WebSocket。
        self._connections: dict[str, WebSocket] = {}

    async def close_all(self) -> None:
        """关闭并清空当前管理器持有的全部连接。"""
        connections = list(self._connections.items())
        try:
            for user_id, websocket in connections:
                try:
                    await websocket.close(
                        code=SERVICE_SHUTDOWN_CODE,
                        reason=SERVICE_SHUTDOWN_REASON,
                    )
                except Exception:
                    logger.exception("关闭用户 %s 的 WebSocket 连接失败", user_id)
        finally:
            self._connections.clear()

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

        old_websocket = self._connections.get(user_id)
        self._connections[user_id] = websocket
        if old_websocket is not None and old_websocket is not websocket:
            try:
                await old_websocket.close(
                    code=DUPLICATE_CONNECTION_CODE,
                    reason=DUPLICATE_CONNECTION_REASON,
                )
            except Exception:
                logger.exception("关闭用户 %s 被替换的 WebSocket 连接失败", user_id)

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

        # 获取当前连接，避免在线检查与读取连接使用两次查询。
        websocket = self._connections.get(sender_id)
        if websocket is None:
            return False

        try:
            await websocket.send_json(data)
        except (WebSocketDisconnect, RuntimeError, OSError):
            # 发送期间连接失效时，仅清理本次取得的连接。
            self.disconnect(user_id=sender_id, websocket=websocket)
            return False

        return True


# 将局部 ConnectionManager 提升为模块级单例，使不同连接的用户可以互相发现和通信。
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用持有的连接管理器生命周期。"""
    app.state.connection_manager = manager
    try:
        yield
    finally:
        await manager.close_all()


app = FastAPI(lifespan=lifespan)


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
    await manager.connect(user_id=user_id, websocket=websocket)

    try:
        # 当前没有空闲超时或在线状态时效需求，暂不增加应用级心跳。
        while True:
            # 等待 websocket 接受文本
            raw_message = (
                await websocket.receive_text()
            )  # 这里一定要 await, 因为要等待接受 receive_text, 是一个异步
            # 先验证一下 raw_message 是不是合法的
            client_message_id: UUID | None = None
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
            # 自发消息规则：允许发送，并将当前连接作为目标连接。
            recipient_id = send_message_command.recipient_id
            target_user_id = user_id if recipient_id == user_id else recipient_id

            if not manager.is_online(user_id=target_user_id):
                offline_error = ErrorEvent(
                    code="recipient_offline",
                    message=f"用户 {target_user_id} 不在线",
                    client_message_id=send_message_command.client_message_id,
                )
                await manager.send_message_to_user(
                    sender_id=user_id, data=offline_error.model_dump(mode="json")
                )
                continue

            try:
                chat_message = to_chat_message(
                    send_message_command,
                    sender_id=user_id,
                    recipient_id=target_user_id,
                )
            except DomainError:
                invalid_message_error = ErrorEvent(
                    code="invalid_message",
                    message="消息字段验证失败",
                    client_message_id=send_message_command.client_message_id,
                )
                await manager.send_message_to_user(
                    sender_id=user_id,
                    data=invalid_message_error.model_dump(mode="json"),
                )
                continue

            message_event = to_message_event(chat_message)

            # 发送成功后给 sender 返回 ack 确认。
            if not await manager.send_message_to_user(
                sender_id=chat_message.recipient_id.value,
                data=message_event.model_dump(mode="json"),
            ):
                offline_error = ErrorEvent(
                    code="recipient_offline",
                    message=f"用户 {target_user_id} 当前离线",
                    client_message_id=send_message_command.client_message_id,
                )
                await manager.send_message_to_user(
                    sender_id=user_id, data=offline_error.model_dump(mode="json")
                )
                continue

            ack = {
                "type": "ack",
                "client_message_id": str(chat_message.client_message_id),
                "server_message_id": str(chat_message.message_id),
            }
            await manager.send_message_to_user(sender_id=user_id, data=ack)

    except WebSocketDisconnect:
        # 客户端断开, 结束当前的连接
        manager.disconnect(user_id=user_id, websocket=websocket)
    finally:
        # 接入管理器后，无论正常断开还是发生异常，都调用 disconnect。
        # disconnect 必须只删除与当前 websocket 相同的连接。
        manager.disconnect(user_id=user_id, websocket=websocket)

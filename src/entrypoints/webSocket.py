"""FastAPI WebSocket 输入入口。"""

import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from src.application import (
    AdvanceConversationPositionService,
    AdvancePositionCommand,
    AuthenticationService,
    ConversationStorageError,
    ConversationUnavailable,
    InvalidAccessToken,
    InvalidConversationPosition,
    InvalidMessageHistoryQuery,
    MessageStorageError,
    PositionKind,
    SendMessageCommand,
    SendMessageService,
    SendMessageStatus,
    SyncMessagesCommand,
    SyncMessagesService,
    UserStorageError,
)

logger = logging.getLogger(__name__)

MESSAGE_TOO_LARGE_CODE = 4409
MESSAGE_TOO_LARGE_REASON = "消息超过大小限制"
RATE_LIMIT_CODE = 4408
RATE_LIMIT_REASON = "消息输入频率过高"


class WebSocketConnectionGateway(Protocol):
    """WebSocket 入口需要的最小连接管理能力。"""

    async def connect(self, user_id: str, websocket: WebSocket) -> bool:
        """在容量允许时接受并登记用户连接。"""
        ...

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """删除仍属于用户的指定连接。"""
        ...

    async def send_message_to_user(
        self,
        sender_id: str,
        data: dict[str, object],
    ) -> bool:
        """向用户当前连接发送协议数据。"""
        ...


class InputRateLimiter(Protocol):
    """单连接输入限流器的最小能力。"""

    def tryAcquire(self) -> bool:
        """返回当前命令是否允许处理。"""
        ...


class SendMessagePayload(BaseModel):
    """客户端发送消息的 WebSocket 载荷。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["send_message"]
    conversation_id: UUID
    content: str = Field(min_length=1, max_length=2000)
    client_message_id: UUID

    @field_validator("content")
    @classmethod
    def validateContent(cls, content: str) -> str:
        """规范化并拒绝空白消息内容。"""
        normalizedContent = content.strip()
        if not normalizedContent:
            raise ValueError("发送消息不能为空")
        return normalizedContent


class AcknowledgePositionPayload(BaseModel):
    """客户端累计确认送达或已读位置的载荷。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["acknowledge_position"]
    conversation_id: UUID
    position_type: PositionKind
    message_id: UUID


class SyncMessagesPayload(BaseModel):
    """客户端重连后补偿缺失消息的载荷。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sync_messages"]
    conversation_id: UUID
    after_message_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=100)


ClientPayload = Annotated[
    SendMessagePayload | AcknowledgePositionPayload | SyncMessagesPayload,
    Field(discriminator="type"),
]
CLIENT_PAYLOAD_ADAPTER = TypeAdapter(ClientPayload)


class ErrorEvent(BaseModel):
    """服务端 WebSocket 错误事件。"""

    type: Literal["error"] = "error"
    code: str
    message: str
    client_message_id: UUID | None = None


def messageToEvent(message: Any) -> dict[str, object]:
    """把领域消息转换成实时推送和同步共用的协议结构。"""
    return {
        "type": "message",
        "server_message_id": str(message.message_id),
        "client_message_id": str(message.client_message_id),
        "conversation_id": str(message.conversation_id),
        "sender_id": str(message.sender_id),
        "recipient_id": str(message.recipient_id),
        "content": str(message.content),
        "sent_at": message.created_at.isoformat().replace("+00:00", "Z"),
    }


def create_router(
    *,
    send_message_service: SendMessageService,
    connection_gateway: WebSocketConnectionGateway,
    authenticationService: AuthenticationService,
    positionService: AdvanceConversationPositionService,
    syncService: SyncMessagesService,
    rateLimiterFactory: Callable[[], InputRateLimiter],
    maxMessageBytes: int,
) -> APIRouter:
    """创建已经注入应用服务和连接网关的 FastAPI 路由。"""
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """认证连接并分派发送、累计确认和重连同步命令。"""
        connectionId = str(uuid4())
        authorization = websocket.headers.get("authorization")
        scheme, token = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer" or not token:
            logger.warning(
                "websocket_authentication_rejected",
                extra={
                    "event": "authentication_rejected",
                    "connection_id": connectionId,
                },
            )
            await websocket.close(code=4401, reason="无法验证身份凭证")
            return
        try:
            currentUser = await authenticationService.authenticateAccessToken(token)
        except (InvalidAccessToken, UserStorageError):
            logger.warning(
                "websocket_authentication_rejected",
                extra={
                    "event": "authentication_rejected",
                    "connection_id": connectionId,
                },
            )
            await websocket.close(code=4401, reason="无法验证身份凭证")
            return

        userId = str(currentUser.user_id)
        connected = await connection_gateway.connect(
            user_id=userId,
            websocket=websocket,
        )
        if not connected:
            logger.warning(
                "websocket_connection_rejected",
                extra={
                    "event": "connection_rejected",
                    "connection_id": connectionId,
                    "user_id": userId,
                },
            )
            return
        rateLimiter = rateLimiterFactory()
        logger.info(
            "websocket_connected",
            extra={
                "event": "websocket_connected",
                "connection_id": connectionId,
                "user_id": userId,
            },
        )

        async def sendToCurrent(data: dict[str, object]) -> None:
            """把当前命令的响应发送到仍有效的当前用户连接。"""
            await connection_gateway.send_message_to_user(
                sender_id=userId,
                data=data,
            )

        try:
            while True:
                rawMessage = await websocket.receive_text()
                if len(rawMessage.encode("utf-8")) > maxMessageBytes:
                    logger.warning(
                        "websocket_message_too_large",
                        extra={
                            "event": "message_rejected",
                            "connection_id": connectionId,
                            "user_id": userId,
                            "status": "message_too_large",
                        },
                    )
                    await sendToCurrent(
                        ErrorEvent(
                            code="message_too_large",
                            message="消息超过大小限制",
                        ).model_dump(mode="json")
                    )
                    await websocket.close(
                        code=MESSAGE_TOO_LARGE_CODE,
                        reason=MESSAGE_TOO_LARGE_REASON,
                    )
                    return
                if not rateLimiter.tryAcquire():
                    logger.warning(
                        "websocket_rate_limited",
                        extra={
                            "event": "message_rejected",
                            "connection_id": connectionId,
                            "user_id": userId,
                            "status": "rate_limited",
                        },
                    )
                    await sendToCurrent(
                        ErrorEvent(
                            code="rate_limited",
                            message="消息输入频率过高",
                        ).model_dump(mode="json")
                    )
                    await websocket.close(
                        code=RATE_LIMIT_CODE,
                        reason=RATE_LIMIT_REASON,
                    )
                    return
                try:
                    payload = CLIENT_PAYLOAD_ADAPTER.validate_json(rawMessage)
                except ValidationError as validationError:
                    firstError = validationError.errors()[0]
                    errorCode = (
                        "invalid_json"
                        if firstError["type"] == "json_invalid"
                        else "invalid_message"
                    )
                    await sendToCurrent(
                        ErrorEvent(
                            code=errorCode,
                            message="消息格式验证失败",
                        ).model_dump(mode="json")
                    )
                    logger.warning(
                        "websocket_protocol_rejected",
                        extra={
                            "event": "message_rejected",
                            "connection_id": connectionId,
                            "user_id": userId,
                            "status": errorCode,
                        },
                    )
                    continue

                if isinstance(payload, SendMessagePayload):
                    result = await send_message_service.send(
                        SendMessageCommand(
                            sender_id=userId,
                            conversation_id=payload.conversation_id,
                            content=payload.content,
                            client_message_id=payload.client_message_id,
                        )
                    )
                    if result.status is SendMessageStatus.ACCEPTED:
                        if result.message is None or result.push_outcome is None:
                            raise RuntimeError("接受消息结果缺少消息或推送观测")
                        await sendToCurrent(
                            {
                                "type": "accepted",
                                "client_message_id": str(
                                    result.message.client_message_id
                                ),
                                "server_message_id": str(result.message.message_id),
                                "conversation_id": str(result.message.conversation_id),
                                "push_status": result.push_outcome.value,
                            }
                        )
                        logger.info(
                            "message_accepted",
                            extra={
                                "event": "message_accepted",
                                "connection_id": connectionId,
                                "user_id": userId,
                                "conversation_id": str(result.message.conversation_id),
                                "client_message_id": str(
                                    result.message.client_message_id
                                ),
                                "server_message_id": str(result.message.message_id),
                                "status": result.push_outcome.value,
                            },
                        )
                        continue

                    errorByStatus = {
                        SendMessageStatus.STORAGE_FAILED: (
                            "message_storage_failed",
                            "消息保存失败",
                        ),
                        SendMessageStatus.INVALID_MESSAGE: (
                            "invalid_message",
                            "消息字段验证失败",
                        ),
                        SendMessageStatus.CONVERSATION_UNAVAILABLE: (
                            "conversation_unavailable",
                            "无法创建或访问该会话",
                        ),
                    }
                    errorCode, errorMessage = errorByStatus[result.status]
                    logLevel = (
                        logging.WARNING
                        if result.status is SendMessageStatus.CONVERSATION_UNAVAILABLE
                        else logging.ERROR
                    )
                    logger.log(
                        logLevel,
                        "message_command_rejected",
                        extra={
                            "event": "authorization_rejected",
                            "connection_id": connectionId,
                            "user_id": userId,
                            "conversation_id": str(payload.conversation_id),
                            "client_message_id": str(payload.client_message_id),
                            "status": errorCode,
                        },
                    )
                    await sendToCurrent(
                        ErrorEvent(
                            code=errorCode,
                            message=errorMessage,
                            client_message_id=payload.client_message_id,
                        ).model_dump(mode="json")
                    )
                    continue

                if isinstance(payload, AcknowledgePositionPayload):
                    try:
                        result = await positionService.advance(
                            AdvancePositionCommand(
                                user_id=userId,
                                conversation_id=payload.conversation_id,
                                message_id=payload.message_id,
                                kind=payload.position_type,
                            )
                        )
                    except ConversationUnavailable:
                        errorCode = "conversation_unavailable"
                        errorMessage = "无法创建或访问该会话"
                    except InvalidConversationPosition:
                        errorCode = "invalid_position"
                        errorMessage = "确认位置无效"
                    except (ConversationStorageError, MessageStorageError):
                        errorCode = "position_storage_failed"
                        errorMessage = "确认位置保存失败"
                    else:
                        await sendToCurrent(
                            {
                                "type": "position_ack",
                                "conversation_id": str(payload.conversation_id),
                                "position_type": result.kind.value,
                                "message_id": (
                                    str(result.effective_position.message_id)
                                    if result.effective_position is not None
                                    else None
                                ),
                                "advanced": result.advanced,
                            }
                        )
                        continue
                    await sendToCurrent(
                        ErrorEvent(code=errorCode, message=errorMessage).model_dump(
                            mode="json"
                        )
                    )
                    continue

                try:
                    syncResult = await syncService.sync(
                        SyncMessagesCommand(
                            user_id=userId,
                            conversation_id=payload.conversation_id,
                            after_message_id=payload.after_message_id,
                            limit=payload.limit,
                        )
                    )
                except ConversationUnavailable:
                    errorCode = "conversation_unavailable"
                    errorMessage = "无法创建或访问该会话"
                except (InvalidConversationPosition, InvalidMessageHistoryQuery):
                    errorCode = "invalid_position"
                    errorMessage = "同步位置无效"
                except (ConversationStorageError, MessageStorageError):
                    errorCode = "sync_storage_failed"
                    errorMessage = "缺失消息同步失败"
                else:
                    await sendToCurrent(
                        {
                            "type": "sync_result",
                            "conversation_id": str(payload.conversation_id),
                            "messages": [
                                messageToEvent(message)
                                for message in syncResult.messages
                            ],
                            "has_more": syncResult.has_more,
                        }
                    )
                    continue
                await sendToCurrent(
                    ErrorEvent(code=errorCode, message=errorMessage).model_dump(
                        mode="json"
                    )
                )
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception(
                "websocket_handler_failed",
                extra={
                    "event": "websocket_failed",
                    "connection_id": connectionId,
                    "user_id": userId,
                },
            )
            raise
        finally:
            connection_gateway.disconnect(user_id=userId, websocket=websocket)
            logger.info(
                "websocket_disconnected",
                extra={
                    "event": "websocket_disconnected",
                    "connection_id": connectionId,
                    "user_id": userId,
                },
            )

    return router

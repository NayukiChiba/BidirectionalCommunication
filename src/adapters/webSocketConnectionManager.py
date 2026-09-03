"""单进程 WebSocket 连接管理适配器。"""

import logging
import warnings
from enum import StrEnum

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

DUPLICATE_CONNECTION_CODE = 4001
DUPLICATE_CONNECTION_REASON = "该账号已在其他连接登录"
SERVICE_SHUTDOWN_CODE = 1001
SERVICE_SHUTDOWN_REASON = "服务停止"


class ConnectionSendOutcome(StrEnum):
    """连接管理器的一次实际发送结果。"""

    DELIVERED = "delivered"
    RECIPIENT_OFFLINE = "recipient_offline"
    FAILED = "failed"


class ConnectionManager:
    """管理当前进程中的用户 WebSocket 连接。"""

    def __init__(self) -> None:
        """初始化在线连接表。"""
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
        """接受连接，并将它登记为用户的当前有效连接。"""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id 不可以为空")

        await websocket.accept()

        old_websocket = self._connections.get(normalized_user_id)
        self._connections[normalized_user_id] = websocket
        if old_websocket is not None and old_websocket is not websocket:
            try:
                await old_websocket.close(
                    code=DUPLICATE_CONNECTION_CODE,
                    reason=DUPLICATE_CONNECTION_REASON,
                )
            except Exception:
                logger.exception(
                    "关闭用户 %s 被替换的 WebSocket 连接失败",
                    normalized_user_id,
                )

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """仅在连接仍是当前连接时将其删除。"""
        current_websocket = self._connections.get(user_id)
        if current_websocket is not websocket:
            return False

        self._connections.pop(user_id)
        return True

    def is_online(self, user_id: str) -> bool:
        """判断用户当前是否拥有已登记连接。"""
        return user_id in self._connections

    async def send_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> bool:
        """通过旧接口发送 JSON 数据。"""
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
        """发送 JSON 数据，并保留旧参数兼容行为。"""
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

        outcome = await self.deliver_to_user(user_id=sender_id, data=data)
        return outcome is ConnectionSendOutcome.DELIVERED

    async def deliver_to_user(
        self,
        user_id: str,
        data: dict[str, object],
    ) -> ConnectionSendOutcome:
        """执行一次连接发送，并明确区分离线和发送失败。"""
        websocket = self._connections.get(user_id)
        if websocket is None:
            return ConnectionSendOutcome.RECIPIENT_OFFLINE

        try:
            await websocket.send_json(data)
        except (WebSocketDisconnect, RuntimeError, OSError):
            self.disconnect(user_id=user_id, websocket=websocket)
            return ConnectionSendOutcome.FAILED

        return ConnectionSendOutcome.DELIVERED

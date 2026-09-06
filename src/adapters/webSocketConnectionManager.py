"""单进程 WebSocket 连接管理适配器。"""

import logging
from enum import StrEnum

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

DUPLICATE_CONNECTION_CODE = 4001
DUPLICATE_CONNECTION_REASON = "该账号已在其他连接登录"
SERVICE_SHUTDOWN_CODE = 1001
SERVICE_SHUTDOWN_REASON = "服务停止"
CONNECTION_LIMIT_CODE = 4429
CONNECTION_LIMIT_REASON = "连接容量已满"
SERVICE_NOT_ACCEPTING_CODE = 1013
SERVICE_NOT_ACCEPTING_REASON = "服务正在停止"


class ConnectionSendOutcome(StrEnum):
    """连接管理器的一次实际发送结果。"""

    DELIVERED = "delivered"
    RECIPIENT_OFFLINE = "recipient_offline"
    FAILED = "failed"


class ConnectionManager:
    """管理当前进程中的用户 WebSocket 连接。"""

    def __init__(self, maxConnections: int = 1_000) -> None:
        """初始化在线连接表和单实例连接容量。"""
        if maxConnections < 1:
            raise ValueError("最大连接数必须大于零")
        self._connections: dict[str, WebSocket] = {}
        self._maxConnections = maxConnections
        self._acceptingConnections = True

    @property
    def connectionCount(self) -> int:
        """返回当前进程已登记的连接数量。"""
        return len(self._connections)

    @property
    def acceptingConnections(self) -> bool:
        """返回管理器是否仍允许登记新连接。"""
        return self._acceptingConnections

    def stopAccepting(self) -> None:
        """在优雅关闭开始时拒绝登记新连接。"""
        self._acceptingConnections = False

    async def close_all(self) -> None:
        """关闭并清空当前管理器持有的全部连接。"""
        self.stopAccepting()
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

    async def connect(self, user_id: str, websocket: WebSocket) -> bool:
        """在服务和容量允许时接受并登记用户连接。"""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id 不可以为空")

        if not self._acceptingConnections:
            await websocket.accept()
            await websocket.close(
                code=SERVICE_NOT_ACCEPTING_CODE,
                reason=SERVICE_NOT_ACCEPTING_REASON,
            )
            return False

        isNewUser = normalized_user_id not in self._connections
        if isNewUser and self.connectionCount >= self._maxConnections:
            await websocket.accept()
            await websocket.close(
                code=CONNECTION_LIMIT_CODE,
                reason=CONNECTION_LIMIT_REASON,
            )
            return False

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
        return True

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

    async def send_message_to_user(
        self,
        sender_id: str,
        data: dict[str, object],
    ) -> bool:
        """向指定用户发送 JSON 数据。"""
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

"""
Connection Manager 单元测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters import (
    DUPLICATE_CONNECTION_CODE,
    DUPLICATE_CONNECTION_REASON,
    SERVICE_SHUTDOWN_CODE,
    SERVICE_SHUTDOWN_REASON,
    ConnectionManager,
)


class TestConnectionManager:
    """
    Connection Manager 单元测试套件
    """

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        """
        Returns: 每个测试用力都使用全新的管理器实例
        """
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self) -> MagicMock:
        """
        Returns: MagicMock 创建 mock Websocket, accept 和 send_json 为异步 mock
        """
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    # ===== connect test 连接测试 =====
    @pytest.mark.asyncio
    async def test_connect_stores_user(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """
        测试连接检测 user在线
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        await manager.connect(user_id="user-a", websocket=mock_websocket)
        assert manager.is_online("user-a") is True

    @pytest.mark.asyncio
    async def test_connect_calls_accept(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """
        使用 connect 方法的时候, 应该要调用 websocket.accpet() 方法
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        await manager.connect(user_id="user-a", websocket=mock_websocket)
        assert mock_websocket.accept.await_count == 1

    @pytest.mark.asyncio
    async def test_connect_empty_user_id_raises_error(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """
        测试连接空 user_id 的时候出现 raise error
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        with pytest.raises(ValueError):
            await manager.connect(user_id="    ", websocket=mock_websocket)

    @pytest.mark.asyncio
    async def test_duplicate_connection_replaces_and_closes_old_connection(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """新连接应替换并按稳定原因关闭旧连接。"""
        new_websocket = MagicMock()
        new_websocket.accept = AsyncMock()
        new_websocket.close = AsyncMock()

        await manager.connect("user-a", mock_websocket)
        await manager.connect("user-a", new_websocket)

        mock_websocket.close.assert_awaited_once_with(
            code=DUPLICATE_CONNECTION_CODE,
            reason=DUPLICATE_CONNECTION_REASON,
        )
        assert manager._connections["user-a"] is new_websocket

    @pytest.mark.asyncio
    async def test_replaced_connection_cannot_remove_current_connection(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """旧连接晚退出时不能删除已登记的新连接。"""
        new_websocket = MagicMock()
        new_websocket.accept = AsyncMock()
        new_websocket.close = AsyncMock()

        await manager.connect("user-a", mock_websocket)
        await manager.connect("user-a", new_websocket)

        assert manager.disconnect("user-a", mock_websocket) is False
        assert manager._connections["user-a"] is new_websocket

    # ===== disconnect =====
    @pytest.mark.asyncio
    async def test_disconnect_removes_user(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """
        正常断开连接之后 user 为不在线状态
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        await manager.connect(user_id="user-a", websocket=mock_websocket)
        result = manager.disconnect(user_id="user-a", websocket=mock_websocket)
        assert result is True
        assert manager.is_online("user-a") is False

    def test_disconnect_user_not_online(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """
        断开不在线用户返回 False
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        result = manager.disconnect(user_id="user-a", websocket=mock_websocket)
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_wrong_websocket(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """
        使用错误的 WebSocket 断开失败, 用户仍然在线
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        await manager.connect(user_id="user-a", websocket=mock_websocket)
        other_websocket = MagicMock()
        result = manager.disconnect(user_id="user-a", websocket=other_websocket)
        assert result is False
        assert manager.is_online("user-a") is True

    # ===== is_online =====
    def test_is_online_for_unknown_user(self, manager: ConnectionManager) -> None:
        """
        测试未连接用户返回 False
        Args:
            manager(ConnectionManager): 连接管理器
        """
        assert manager.is_online("user-a") is False

    # ===== send_message_to_user =====
    @pytest.mark.asyncio
    async def test_send_message_to_user_calls_send_json(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """
        测试在线用户发送消息的时候调用 send_json
        Args:
            manager(ConnectionManager): 连接管理器
            mock_websocket(MagicMock): mock 的 websocket 连接
        """
        await manager.connect(user_id="user-a", websocket=mock_websocket)
        data = {"type": "message", "content": "hello"}
        result = await manager.send_message_to_user(sender_id="user-a", data=data)
        assert result is True
        assert mock_websocket.send_json.await_count == 1

    @pytest.mark.asyncio
    async def test_send_to_offline_user(self, manager: ConnectionManager) -> None:
        """
        测试离线用户发送消息
        Args:
            manager(ConnectionManager): 连接管理器
        """
        result = await manager.send_message_to_user(
            sender_id="user-a",
            data={"type": "message"},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_failure_removes_stale_connection(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """测试发送期间连接失效时清理失效连接"""
        mock_websocket.send_json.side_effect = RuntimeError("连接已关闭")
        await manager.connect(user_id="user-a", websocket=mock_websocket)

        result = await manager.send_message_to_user(
            sender_id="user-a",
            data={"type": "message"},
        )

        assert result is False
        assert manager.is_online("user-a") is False

    @pytest.mark.asyncio
    async def test_send_failure_does_not_remove_replacement(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """发送失败期间发生连接替换时保留新连接。"""
        replacement = MagicMock()
        replacement.accept = AsyncMock()
        replacement.close = AsyncMock()

        async def replace_then_fail(data: dict[str, object]) -> None:
            await manager.connect("user-a", replacement)
            raise RuntimeError("旧连接已关闭")

        mock_websocket.send_json.side_effect = replace_then_fail
        await manager.connect("user-a", mock_websocket)

        result = await manager.send_message_to_user(
            sender_id="user-a", data={"type": "message"}
        )

        assert result is False
        assert manager._connections["user-a"] is replacement

    @pytest.mark.asyncio
    async def test_close_all_continues_after_failure(
        self, manager: ConnectionManager, mock_websocket: MagicMock
    ) -> None:
        """停止清理应忽略单个关闭失败并清空连接表。"""
        failing_websocket = MagicMock()
        failing_websocket.accept = AsyncMock()
        failing_websocket.close = AsyncMock(side_effect=RuntimeError("关闭失败"))

        await manager.connect("user-a", failing_websocket)
        await manager.connect("user-b", mock_websocket)
        await manager.close_all()

        mock_websocket.close.assert_awaited_once_with(
            code=SERVICE_SHUTDOWN_CODE,
            reason=SERVICE_SHUTDOWN_REASON,
        )
        assert manager._connections == {}

    @pytest.mark.asyncio
    async def test_send_message_to_user_accepts_legacy_user_id(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """测试兼容 user_id 参数并发出弃用警告"""
        await manager.connect(user_id="user-a", websocket=mock_websocket)

        with pytest.warns(DeprecationWarning, match="user_id 参数已弃用"):
            result = await manager.send_message_to_user(
                user_id="user-a",
                data={"type": "message"},
            )

        assert result is True
        mock_websocket.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_to_user_rejects_both_user_ids(
        self,
        manager: ConnectionManager,
    ) -> None:
        """测试不能同时提供 sender_id 和 user_id"""
        with pytest.raises(TypeError, match="不能同时提供"):
            await manager.send_message_to_user(
                sender_id="user-a",
                user_id="user-b",
                data={"type": "message"},
            )

    @pytest.mark.asyncio
    async def test_send_to_user_emits_deprecation_warning(
        self,
        manager: ConnectionManager,
        mock_websocket: MagicMock,
    ) -> None:
        """测试旧函数保持可用并发出弃用警告"""
        await manager.connect(user_id="user-a", websocket=mock_websocket)

        with pytest.warns(DeprecationWarning, match=r"send_to_user\(\) 已弃用"):
            result = await manager.send_to_user(
                user_id="user-a",
                data={"type": "message"},
            )

        assert result is True
        mock_websocket.send_json.assert_awaited_once()

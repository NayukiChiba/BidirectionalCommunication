"""
Connection Manager 单元测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from main import ConnectionManager


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
    async def test_connect_calls_accpet(
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

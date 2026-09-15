"""数据库就绪探针的驱动层异常测试。"""

from typing import cast

import pytest
from asyncpg.exceptions import ConnectionDoesNotExistError
from sqlalchemy.ext.asyncio import AsyncEngine

from src.adapters.database import DatabaseReadinessProbe


class ClosedConnectionContext:
    """模拟 asyncpg 在 SQLAlchemy 建立连接时直接中断。"""

    async def __aenter__(self) -> None:
        """进入连接上下文时抛出真实驱动层异常类型。"""
        raise ConnectionDoesNotExistError("connection closed during operation")

    async def __aexit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        """连接未成功建立，不需要清理资源。"""


class ClosedConnectionEngine:
    """返回连接中断上下文的最小异步引擎替身。"""

    def connect(self) -> ClosedConnectionContext:
        """创建连接中断上下文。"""
        return ClosedConnectionContext()


@pytest.mark.asyncio
async def test_readiness_returns_false_when_asyncpg_connection_closes() -> None:
    """驱动层连接中断应返回未就绪，而不是泄漏为 HTTP 500。"""
    engine = cast(AsyncEngine, ClosedConnectionEngine())
    probe = DatabaseReadinessProbe(
        engine=engine,
        expectedRevision="expected-revision",
        timeoutSeconds=0.5,
    )

    assert await probe.isReady() is False

"""数据库连接和迁移版本就绪状态探测。"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class DatabaseReadinessProbe:
    """通过短查询确认数据库可连接且迁移版本正确。"""

    def __init__(
        self,
        engine: AsyncEngine,
        expectedRevision: str,
        timeoutSeconds: float,
    ) -> None:
        """保存数据库引擎、预期迁移版本和超时。"""
        self._engine = engine
        self._expectedRevision = expectedRevision
        self._timeoutSeconds = timeoutSeconds

    async def isReady(self) -> bool:
        """返回数据库能否承接当前版本请求。"""
        try:
            async with asyncio.timeout(self._timeoutSeconds):
                async with self._engine.connect() as connection:
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
        except (TimeoutError, SQLAlchemyError):
            logger.warning("database_readiness_failed", extra={"event": "readiness"})
            return False
        return revision == self._expectedRevision

"""低成本存活与就绪检查入口。"""

from typing import Protocol

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse


class ReadinessProbe(Protocol):
    """就绪接口依赖的最小异步探测能力。"""

    async def isReady(self) -> bool:
        """返回应用依赖是否能够承接请求。"""
        ...


def createHealthRouter(readinessProbe: ReadinessProbe) -> APIRouter:
    """创建存活、兼容和数据库就绪路由。"""
    router = APIRouter(tags=["health"])

    @router.get("/health")
    @router.get("/health/live")
    async def getLiveness() -> dict[str, str]:
        """只确认进程事件循环仍可响应，不访问外部依赖。"""
        return {"status": "alive"}

    @router.get("/health/ready")
    async def getReadiness() -> JSONResponse:
        """通过轻量数据库版本查询决定是否接收业务流量。"""
        if await readinessProbe.isReady():
            return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return router

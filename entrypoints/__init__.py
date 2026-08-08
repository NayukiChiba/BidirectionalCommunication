"""应用的外部请求入口。"""

from entrypoints.webSocket import create_router

__all__ = ["create_router"]

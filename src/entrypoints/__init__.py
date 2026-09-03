"""应用的外部请求入口。"""

from src.entrypoints.webSocket import create_router

__all__ = ["create_router"]

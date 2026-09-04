"""应用的外部请求入口。"""

from src.entrypoints.authentication import (
    CurrentUserDependency,
    createAuthenticationRouter,
)
from src.entrypoints.messageHistory import createHistoryRouter
from src.entrypoints.webSocket import create_router

__all__ = [
    "CurrentUserDependency",
    "createAuthenticationRouter",
    "createHistoryRouter",
    "create_router",
]

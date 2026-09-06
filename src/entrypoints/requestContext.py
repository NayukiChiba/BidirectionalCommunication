"""HTTP 请求关联 ID 和安全访问日志。"""

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)


def addRequestContextMiddleware(app: FastAPI) -> None:
    """为每个 HTTP 请求生成服务端关联 ID 并记录安全元数据。"""

    @app.middleware("http")
    async def requestContext(request: Request, callNext) -> Response:
        requestId = str(uuid4())
        request.state.requestId = requestId
        startedAt = time.monotonic()
        context = {
            "event": "http_request",
            "request_id": requestId,
            "method": request.method,
            "path": request.url.path,
        }
        try:
            response = await callNext(request)
        except Exception:
            logger.exception(
                "http_request_failed",
                extra={**context, "status": 500},
            )
            raise

        response.headers["X-Request-ID"] = requestId
        logger.info(
            "http_request_completed",
            extra={
                **context,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - startedAt) * 1_000, 3),
            },
        )
        return response

"""不记录敏感业务数据的 JSON 结构化日志配置。"""

import json
import logging
from datetime import datetime, timezone

SAFE_CONTEXT_FIELDS = (
    "event",
    "request_id",
    "connection_id",
    "user_id",
    "conversation_id",
    "client_message_id",
    "server_message_id",
    "command_type",
    "status",
    "method",
    "path",
    "duration_ms",
    "connection_count",
)


class JsonLogFormatter(logging.Formatter):
    """仅输出固定安全上下文字段的单行 JSON 日志。"""

    def format(self, record: logging.LogRecord) -> str:
        """把 LogRecord 转换为不包含正文、密码和令牌的 JSON。"""
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for fieldName in SAFE_CONTEXT_FIELDS:
            value = getattr(record, fieldName, None)
            if value is not None:
                payload[fieldName] = value
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configureStructuredLogging(logLevel: str) -> None:
    """为项目日志器安装统一 JSON 输出，不改写第三方日志配置。"""
    # Alembic 在同进程测试中加载 logging.ini 后可能禁用已有应用日志器。
    for loggerName, loggerObject in logging.Logger.manager.loggerDict.items():
        if isinstance(loggerObject, logging.Logger) and (
            loggerName == "bootstrap" or loggerName.startswith("src.")
        ):
            loggerObject.disabled = False

    for loggerName in ("src", "bootstrap"):
        applicationLogger = logging.getLogger(loggerName)
        applicationLogger.disabled = False
        applicationLogger.setLevel(logLevel)
        applicationLogger.propagate = False
        existingHandler = next(
            (
                handler
                for handler in applicationLogger.handlers
                if getattr(handler, "_bidirectionalJsonHandler", False)
            ),
            None,
        )
        if existingHandler is not None:
            existingHandler.setLevel(logLevel)
            continue

        handler = logging.StreamHandler()
        handler.setLevel(logLevel)
        handler.setFormatter(JsonLogFormatter())
        handler._bidirectionalJsonHandler = True  # type: ignore[attr-defined]
        applicationLogger.addHandler(handler)

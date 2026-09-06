"""结构化日志关联能力与敏感信息保护测试。"""

import io
import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient

from src.observability import JsonLogFormatter
from tests.conftest import AuthenticatedTestUser


def test_json_formatter_keeps_safe_context_and_drops_sensitive_extras() -> None:
    """JSON 日志只能输出白名单上下文，不接受正文、密码或令牌字段。"""
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("tests.safe-logging")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "message_accepted",
        extra={
            "event": "message_accepted",
            "connection_id": "connection-1",
            "client_message_id": "message-1",
            "content": "private-message-body",
            "password": "plain-password",
            "token": "complete-access-token",
        },
    )

    rendered = output.getvalue()
    payload = json.loads(rendered)
    assert payload["event"] == "message_accepted"
    assert payload["connection_id"] == "connection-1"
    assert payload["client_message_id"] == "message-1"
    assert "private-message-body" not in rendered
    assert "plain-password" not in rendered
    assert "complete-access-token" not in rendered


def test_websocket_message_logs_share_connection_id_without_content(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """一次连接和消息流程可关联，但日志不包含私聊正文。"""
    user = authenticatedUsers["user-a"]
    privateContent = "do-not-log-this-private-message"
    records: list[logging.LogRecord] = []

    class ListHandler(logging.Handler):
        """把跨线程产生的记录保存到测试列表。"""

        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    webSocketLogger = logging.getLogger("src.entrypoints.webSocket")
    handler = ListHandler()
    webSocketLogger.addHandler(handler)
    previousLevel = webSocketLogger.level
    webSocketLogger.setLevel(logging.INFO)

    try:
        with testClient.websocket_connect(
            "/ws",
            headers=user.authorizationHeaders,
        ) as websocket:
            websocket.send_json(
                {
                    "type": "send_message",
                    "conversation_id": conversationId,
                    "content": privateContent,
                    "client_message_id": str(uuid4()),
                }
            )
            assert websocket.receive_json()["type"] == "accepted"
    finally:
        webSocketLogger.removeHandler(handler)
        webSocketLogger.setLevel(previousLevel)

    connectionIds = {
        record.connection_id for record in records if hasattr(record, "connection_id")
    }
    assert any(record.getMessage() == "message_accepted" for record in records)
    assert len(connectionIds) == 1
    assert privateContent not in "\n".join(str(vars(record)) for record in records)

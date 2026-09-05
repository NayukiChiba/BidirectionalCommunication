"""累计送达、已读位置与 WebSocket 重连补偿验收测试。"""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.adapters.database.migrationConfig import createMigrationEngine
from tests.conftest import AuthenticatedTestUser


def sendMessage(
    websocket,
    *,
    conversationId: str,
    content: str,
) -> dict[str, object]:
    """发送消息并返回发送方的持久化确认。"""
    websocket.send_json(
        {
            "type": "send_message",
            "conversation_id": conversationId,
            "content": content,
            "client_message_id": str(uuid4()),
        }
    )
    return websocket.receive_json()


def syncMessages(
    websocket,
    *,
    conversationId: str,
    afterMessageId: str | None = None,
) -> dict[str, object]:
    """提交客户端最后已知位置并返回缺失消息。"""
    websocket.send_json(
        {
            "type": "sync_messages",
            "conversation_id": conversationId,
            "after_message_id": afterMessageId,
        }
    )
    return websocket.receive_json()


def acknowledgePosition(
    websocket,
    *,
    conversationId: str,
    positionType: str,
    messageId: str,
) -> dict[str, object]:
    """提交累计送达或已读确认并返回服务端有效位置。"""
    websocket.send_json(
        {
            "type": "acknowledge_position",
            "conversation_id": conversationId,
            "position_type": positionType,
            "message_id": messageId,
        }
    )
    return websocket.receive_json()


def loadMemberPositions(
    application: FastAPI,
    *,
    conversationId: str,
    userId: str,
) -> tuple[str | None, str | None]:
    """通过独立连接读取成员累计位置。"""
    databasePath = Path(application.state.database_engine.url.database)
    engine = createMigrationEngine(databasePath)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT delivered_message_id, read_message_id "
                    "FROM conversation_members "
                    "WHERE conversation_id = :conversationId AND user_id = :userId"
                ),
                {"conversationId": conversationId, "userId": userId},
            ).one()
    finally:
        engine.dispose()
    return row.delivered_message_id, row.read_message_id


def countMessages(application: FastAPI, conversationId: str) -> int:
    """统计一个会话中的持久化领域消息行数。"""
    databasePath = Path(application.state.database_engine.url.database)
    engine = createMigrationEngine(databasePath)
    try:
        with engine.connect() as connection:
            return int(
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM messages "
                        "WHERE conversation_id = :conversationId"
                    ),
                    {"conversationId": conversationId},
                )
                or 0
            )
    finally:
        engine.dispose()


def test_offline_accepted_message_is_recovered_and_sync_advances_delivery(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """离线未推送消息仍被接受，重连同步后由客户端显式推进送达位置。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        accepted = sendMessage(
            senderWebSocket,
            conversationId=conversationId,
            content="offline-message",
        )

    assert accepted["type"] == "accepted"
    assert accepted["push_status"] == "recipient_offline"
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (None, None)

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as recipientWebSocket:
        firstSync = syncMessages(
            recipientWebSocket,
            conversationId=conversationId,
        )
        messageId = firstSync["messages"][0]["server_message_id"]
        completedSync = syncMessages(
            recipientWebSocket,
            conversationId=conversationId,
            afterMessageId=messageId,
        )

    assert [item["content"] for item in firstSync["messages"]] == ["offline-message"]
    assert completedSync["messages"] == []
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (messageId, None)


def test_pushed_but_unconfirmed_message_remains_undelivered_until_reconnect(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """服务端写入 WebSocket 不会代替接收客户端的显式送达确认。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as recipientWebSocket:
        with testClient.websocket_connect(
            "/ws", headers=userA.authorizationHeaders
        ) as senderWebSocket:
            senderWebSocket.send_json(
                {
                    "type": "send_message",
                    "conversation_id": conversationId,
                    "content": "received-not-confirmed",
                    "client_message_id": str(uuid4()),
                }
            )
            pushedMessage = recipientWebSocket.receive_json()
            accepted = senderWebSocket.receive_json()

    messageId = pushedMessage["server_message_id"]
    assert accepted["push_status"] == "pushed"
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (None, None)

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as reconnectedWebSocket:
        syncResult = syncMessages(
            reconnectedWebSocket,
            conversationId=conversationId,
            afterMessageId=messageId,
        )

    assert syncResult["messages"] == []
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (messageId, None)


def test_delivery_and_read_positions_are_monotonic_and_idempotent(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """累计位置拒绝已读越界，并忽略重复或倒序确认。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        sendMessage(
            senderWebSocket,
            conversationId=conversationId,
            content="first",
        )
        sendMessage(
            senderWebSocket,
            conversationId=conversationId,
            content="second",
        )

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as recipientWebSocket:
        synchronized = syncMessages(
            recipientWebSocket,
            conversationId=conversationId,
        )
        firstMessageId, secondMessageId = [
            item["server_message_id"] for item in synchronized["messages"]
        ]

        readBeyondDelivery = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="read",
            messageId=secondMessageId,
        )
        delivered = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="delivered",
            messageId=secondMessageId,
        )
        duplicateDelivered = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="delivered",
            messageId=secondMessageId,
        )
        olderDelivered = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="delivered",
            messageId=firstMessageId,
        )
        read = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="read",
            messageId=secondMessageId,
        )
        olderRead = acknowledgePosition(
            recipientWebSocket,
            conversationId=conversationId,
            positionType="read",
            messageId=firstMessageId,
        )

    assert readBeyondDelivery["code"] == "invalid_position"
    assert delivered["advanced"] is True
    assert duplicateDelivered["advanced"] is False
    assert olderDelivered["advanced"] is False
    assert olderDelivered["message_id"] == secondMessageId
    assert read["advanced"] is True
    assert olderRead["advanced"] is False
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (secondMessageId, secondMessageId)


def test_repeated_sync_is_safe_and_invalid_position_is_rejected(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """相同同步请求返回同一消息身份，伪造位置不能越过会话边界。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        accepted = sendMessage(
            senderWebSocket,
            conversationId=conversationId,
            content="idempotent-sync",
        )

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as recipientWebSocket:
        firstSync = syncMessages(recipientWebSocket, conversationId=conversationId)
        repeatedSync = syncMessages(
            recipientWebSocket,
            conversationId=conversationId,
        )
        invalidSync = syncMessages(
            recipientWebSocket,
            conversationId=conversationId,
            afterMessageId=str(uuid4()),
        )

    firstIds = [item["server_message_id"] for item in firstSync["messages"]]
    repeatedIds = [item["server_message_id"] for item in repeatedSync["messages"]]
    assert firstIds == repeatedIds == [accepted["server_message_id"]]
    assert countMessages(application, conversationId) == 1
    assert invalidSync["type"] == "error"
    assert invalidSync["code"] == "invalid_position"


def test_sender_cannot_forge_another_members_read_position(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
    conversationId: str,
) -> None:
    """确认命令只使用认证身份，载荷不能指定被更新的成员。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        accepted = sendMessage(
            senderWebSocket,
            conversationId=conversationId,
            content="cannot-forge-read",
        )
        senderWebSocket.send_json(
            {
                "type": "acknowledge_position",
                "conversation_id": conversationId,
                "position_type": "read",
                "message_id": accepted["server_message_id"],
                "member_id": userB.userId,
            }
        )
        errorEvent = senderWebSocket.receive_json()

    assert errorEvent["type"] == "error"
    assert errorEvent["code"] == "invalid_message"
    assert loadMemberPositions(
        application,
        conversationId=conversationId,
        userId=userB.userId,
    ) == (None, None)

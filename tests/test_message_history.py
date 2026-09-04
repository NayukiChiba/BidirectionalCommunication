"""历史分页、离线恢复和 WebSocket 幂等验收测试。"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.database.migrationConfig import createMigrationEngine
from src.adapters.database.models import MessageRecord
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)
from tests.conftest import AuthenticatedTestUser


def createMessage(
    *,
    sequence: int,
    senderId: str,
    recipientId: str,
    createdAt: datetime,
) -> ChatMessage:
    """创建具有固定游标顺序的验收消息。"""
    return ChatMessage(
        message_id=MessageId(UUID(int=sequence)),
        client_message_id=ClientMessageId(UUID(int=sequence + 100)),
        sender_id=UserId(senderId),
        recipient_id=UserId(recipientId),
        content=MessageContent(f"message-{sequence}"),
        created_at=createdAt,
    )


def saveMessages(application: FastAPI, messages: tuple[ChatMessage, ...]) -> None:
    """通过同步测试连接准备固定排序的历史数据。"""
    databasePath = Path(application.state.database_engine.url.database)
    engine = createMigrationEngine(databasePath)
    rows = [
        {
            "message_id": str(message.message_id),
            "client_message_id": str(message.client_message_id),
            "sender_id": str(message.sender_id),
            "recipient_id": str(message.recipient_id),
            "content": str(message.content),
            "created_at": message.created_at,
        }
        for message in messages
    ]
    try:
        with engine.begin() as connection:
            connection.execute(MessageRecord.__table__.insert(), rows)
    finally:
        engine.dispose()


def test_history_returns_empty_page(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """没有单聊历史时返回空页。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    response = testClient.get(
        "/messages/history",
        params={"peer_id": userB.userId},
        headers=userA.authorizationHeaders,
    )

    assert response.status_code == 200
    assert response.json() == {
        "messages": [],
        "next_cursor": None,
        "has_more": False,
    }


def test_history_cursor_has_no_duplicates_or_gaps_for_same_timestamp(
    testClient: TestClient,
    application: FastAPI,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """相同时间消息应由消息 ID 稳定决胜并跨页完整返回。"""
    createdAt = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    messages = (
        createMessage(
            sequence=3,
            senderId=userA.userId,
            recipientId=userB.userId,
            createdAt=createdAt,
        ),
        createMessage(
            sequence=1,
            senderId=userB.userId,
            recipientId=userA.userId,
            createdAt=createdAt,
        ),
        createMessage(
            sequence=2,
            senderId=userA.userId,
            recipientId=userB.userId,
            createdAt=createdAt,
        ),
        createMessage(
            sequence=4,
            senderId=userA.userId,
            recipientId="other-user",
            createdAt=createdAt,
        ),
    )
    saveMessages(application, messages)

    firstResponse = testClient.get(
        "/messages/history",
        params={"peer_id": userB.userId, "limit": 2},
        headers=userA.authorizationHeaders,
    )
    firstPage = firstResponse.json()
    secondResponse = testClient.get(
        "/messages/history",
        params={
            "peer_id": userB.userId,
            "limit": 2,
            "cursor": firstPage["next_cursor"],
        },
        headers=userA.authorizationHeaders,
    )
    secondPage = secondResponse.json()

    assert firstResponse.status_code == 200
    assert secondResponse.status_code == 200
    assert [item["content"] for item in firstPage["messages"]] == [
        "message-1",
        "message-2",
    ]
    assert firstPage["has_more"] is True
    assert [item["content"] for item in secondPage["messages"]] == ["message-3"]
    assert secondPage["has_more"] is False
    allMessageIds = [
        item["server_message_id"]
        for item in firstPage["messages"] + secondPage["messages"]
    ]
    assert len(allMessageIds) == len(set(allMessageIds)) == 3


def test_history_rejects_invalid_cursor(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """损坏或伪造的游标应返回稳定查询错误。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    response = testClient.get(
        "/messages/history",
        params={
            "peer_id": userB.userId,
            "cursor": "not-a-valid-cursor",
        },
        headers=userA.authorizationHeaders,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_history_query"


def test_offline_message_can_be_pulled_after_previous_cursor(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """接收者离线期间提交的消息应能通过旧游标主动拉取。"""
    firstClientMessageId = "10000000-0000-0000-0000-000000000001"
    secondClientMessageId = "20000000-0000-0000-0000-000000000002"
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        senderWebSocket.send_json(
            {
                "type": "send_message",
                "recipient_id": userB.userId,
                "content": "before-disconnect",
                "client_message_id": firstClientMessageId,
            }
        )
        assert senderWebSocket.receive_json()["code"] == "recipient_offline"

    firstPage = testClient.get(
        "/messages/history",
        params={"peer_id": userA.userId},
        headers=userB.authorizationHeaders,
    ).json()
    assert [item["content"] for item in firstPage["messages"]] == ["before-disconnect"]

    with testClient.websocket_connect(
        "/ws", headers=userA.authorizationHeaders
    ) as senderWebSocket:
        senderWebSocket.send_json(
            {
                "type": "send_message",
                "recipient_id": userB.userId,
                "content": "while-offline",
                "client_message_id": secondClientMessageId,
            }
        )
        assert senderWebSocket.receive_json()["code"] == "recipient_offline"

    missingPage = testClient.get(
        "/messages/history",
        params={
            "peer_id": userA.userId,
            "cursor": firstPage["next_cursor"],
        },
        headers=userB.authorizationHeaders,
    ).json()
    assert [item["content"] for item in missingPage["messages"]] == ["while-offline"]


def test_duplicate_websocket_command_returns_same_message_without_second_row(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """重复命令可重复推送，但必须返回同一服务端消息且只存一行。"""
    clientMessageId = "30000000-0000-0000-0000-000000000003"
    acknowledgements = []
    deliveredMessages = []
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    with testClient.websocket_connect(
        "/ws", headers=userB.authorizationHeaders
    ) as recipientWebSocket:
        with testClient.websocket_connect(
            "/ws", headers=userA.authorizationHeaders
        ) as senderWebSocket:
            for _ in range(2):
                senderWebSocket.send_json(
                    {
                        "type": "send_message",
                        "recipient_id": userB.userId,
                        "content": "retry-me",
                        "client_message_id": clientMessageId,
                    }
                )
                deliveredMessages.append(recipientWebSocket.receive_json())
                acknowledgements.append(senderWebSocket.receive_json())

    assert (
        deliveredMessages[0]["server_message_id"]
        == deliveredMessages[1]["server_message_id"]
    )
    assert (
        acknowledgements[0]["server_message_id"]
        == acknowledgements[1]["server_message_id"]
    )

    history = testClient.get(
        "/messages/history",
        params={"peer_id": userB.userId},
        headers=userA.authorizationHeaders,
    ).json()
    assert len(history["messages"]) == 1
    assert (
        history["messages"][0]["server_message_id"]
        == acknowledgements[0]["server_message_id"]
    )

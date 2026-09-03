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


def test_history_returns_empty_page(testClient: TestClient) -> None:
    """没有单聊历史时返回空页。"""
    response = testClient.get(
        "/messages/history",
        params={"user_id": "user-a", "peer_id": "user-b"},
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
) -> None:
    """相同时间消息应由消息 ID 稳定决胜并跨页完整返回。"""
    createdAt = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    messages = (
        createMessage(
            sequence=3,
            senderId="user-a",
            recipientId="user-b",
            createdAt=createdAt,
        ),
        createMessage(
            sequence=1,
            senderId="user-b",
            recipientId="user-a",
            createdAt=createdAt,
        ),
        createMessage(
            sequence=2,
            senderId="user-a",
            recipientId="user-b",
            createdAt=createdAt,
        ),
        createMessage(
            sequence=4,
            senderId="user-a",
            recipientId="other-user",
            createdAt=createdAt,
        ),
    )
    saveMessages(application, messages)

    firstResponse = testClient.get(
        "/messages/history",
        params={"user_id": "user-a", "peer_id": "user-b", "limit": 2},
    )
    firstPage = firstResponse.json()
    secondResponse = testClient.get(
        "/messages/history",
        params={
            "user_id": "user-a",
            "peer_id": "user-b",
            "limit": 2,
            "cursor": firstPage["next_cursor"],
        },
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


def test_history_rejects_invalid_cursor(testClient: TestClient) -> None:
    """损坏或伪造的游标应返回稳定查询错误。"""
    response = testClient.get(
        "/messages/history",
        params={
            "user_id": "user-a",
            "peer_id": "user-b",
            "cursor": "not-a-valid-cursor",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_history_query"


def test_offline_message_can_be_pulled_after_previous_cursor(
    testClient: TestClient,
) -> None:
    """接收者离线期间提交的消息应能通过旧游标主动拉取。"""
    firstClientMessageId = "10000000-0000-0000-0000-000000000001"
    secondClientMessageId = "20000000-0000-0000-0000-000000000002"

    with testClient.websocket_connect("/ws?user_id=user-a") as senderWebSocket:
        senderWebSocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "user-b",
                "content": "before-disconnect",
                "client_message_id": firstClientMessageId,
            }
        )
        assert senderWebSocket.receive_json()["code"] == "recipient_offline"

    firstPage = testClient.get(
        "/messages/history",
        params={"user_id": "user-b", "peer_id": "user-a"},
    ).json()
    assert [item["content"] for item in firstPage["messages"]] == ["before-disconnect"]

    with testClient.websocket_connect("/ws?user_id=user-a") as senderWebSocket:
        senderWebSocket.send_json(
            {
                "type": "send_message",
                "recipient_id": "user-b",
                "content": "while-offline",
                "client_message_id": secondClientMessageId,
            }
        )
        assert senderWebSocket.receive_json()["code"] == "recipient_offline"

    missingPage = testClient.get(
        "/messages/history",
        params={
            "user_id": "user-b",
            "peer_id": "user-a",
            "cursor": firstPage["next_cursor"],
        },
    ).json()
    assert [item["content"] for item in missingPage["messages"]] == ["while-offline"]


def test_duplicate_websocket_command_returns_same_message_without_second_row(
    testClient: TestClient,
) -> None:
    """重复命令可重复推送，但必须返回同一服务端消息且只存一行。"""
    clientMessageId = "30000000-0000-0000-0000-000000000003"
    acknowledgements = []
    deliveredMessages = []

    with testClient.websocket_connect("/ws?user_id=user-b") as recipientWebSocket:
        with testClient.websocket_connect("/ws?user_id=user-a") as senderWebSocket:
            for _ in range(2):
                senderWebSocket.send_json(
                    {
                        "type": "send_message",
                        "recipient_id": "user-b",
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
        params={"user_id": "user-a", "peer_id": "user-b"},
    ).json()
    assert len(history["messages"]) == 1
    assert (
        history["messages"][0]["server_message_id"]
        == acknowledgements[0]["server_message_id"]
    )

"""一对一会话身份、成员权限和显式消息目标验收测试。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import (
    TEST_PASSWORD,
    AuthenticatedTestUser,
)


def createConversation(
    client: TestClient,
    currentUser: AuthenticatedTestUser,
    peer: AuthenticatedTestUser,
) -> dict[str, object]:
    """通过公开接口创建或获取会话。"""
    response = client.post(
        "/conversations",
        json={"peer_id": peer.userId},
        headers=currentUser.authorizationHeaders,
    )
    assert response.status_code == 200
    return response.json()


def registerAuthenticatedUser(
    client: TestClient, username: str
) -> AuthenticatedTestUser:
    """注册并登录额外的权限测试用户。"""
    registration = client.post(
        "/auth/register",
        json={"username": username, "password": TEST_PASSWORD},
    )
    login = client.post(
        "/auth/token",
        data={"username": username, "password": TEST_PASSWORD},
    )
    assert registration.status_code == 201
    assert login.status_code == 200
    identity = registration.json()
    return AuthenticatedTestUser(
        userId=identity["user_id"],
        username=identity["username"],
        accessToken=login.json()["access_token"],
    )


def test_create_or_get_returns_same_conversation_for_reversed_members(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """成员输入顺序和重复请求不能创建第二个一对一会话。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]

    first = createConversation(testClient, userA, userB)
    duplicate = createConversation(testClient, userB, userA)

    assert first["created"] is True
    assert duplicate["created"] is False
    assert first["conversation_id"] == duplicate["conversation_id"]
    assert first["member_ids"] == sorted((userA.userId, userB.userId))


def test_self_and_missing_member_conversations_are_rejected(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """会话必须包含两个不同且已经注册的用户。"""
    userA = authenticatedUsers["user-a"]

    selfResponse = testClient.post(
        "/conversations",
        json={"peer_id": userA.userId},
        headers=userA.authorizationHeaders,
    )
    missingResponse = testClient.post(
        "/conversations",
        json={"peer_id": str(uuid4())},
        headers=userA.authorizationHeaders,
    )

    assert selfResponse.status_code == 400
    assert selfResponse.json()["detail"]["code"] == "invalid_conversation"
    assert missingResponse.status_code == 404
    assert missingResponse.json()["detail"]["code"] == "conversation_unavailable"


def test_non_member_cannot_read_or_send_and_cannot_probe_existence(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """认证身份不等于会话成员，拒绝结果也不能泄露会话存在性。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    userC = registerAuthenticatedUser(testClient, "user-c")
    conversation = createConversation(testClient, userA, userB)
    conversationId = str(conversation["conversation_id"])

    forbidden = testClient.get(
        f"/conversations/{conversationId}/messages",
        headers=userC.authorizationHeaders,
    )
    missing = testClient.get(
        f"/conversations/{uuid4()}/messages",
        headers=userC.authorizationHeaders,
    )

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()

    with testClient.websocket_connect(
        "/ws",
        headers=userC.authorizationHeaders,
    ) as websocket:
        websocket.send_json(
            {
                "type": "send_message",
                "conversation_id": conversationId,
                "content": "越权消息",
                "client_message_id": str(uuid4()),
            }
        )
        errorEvent = websocket.receive_json()

    assert errorEvent["type"] == "error"
    assert errorEvent["code"] == "conversation_unavailable"


def test_explicit_conversation_id_sends_to_other_member(
    testClient: TestClient,
    authenticatedUsers: dict[str, AuthenticatedTestUser],
) -> None:
    """新协议只需提供会话 ID，接收者由聚合成员关系决定。"""
    userA = authenticatedUsers["user-a"]
    userB = authenticatedUsers["user-b"]
    conversation = createConversation(testClient, userA, userB)
    clientMessageId = str(uuid4())

    with testClient.websocket_connect(
        "/ws",
        headers=userB.authorizationHeaders,
    ) as recipientWebSocket:
        with testClient.websocket_connect(
            "/ws",
            headers=userA.authorizationHeaders,
        ) as senderWebSocket:
            senderWebSocket.send_json(
                {
                    "type": "send_message",
                    "conversation_id": conversation["conversation_id"],
                    "content": "显式会话消息",
                    "client_message_id": clientMessageId,
                }
            )
            messageEvent = recipientWebSocket.receive_json()
            acknowledgement = senderWebSocket.receive_json()

    assert messageEvent["conversation_id"] == conversation["conversation_id"]
    assert messageEvent["recipient_id"] == userB.userId
    assert acknowledgement["server_message_id"] == messageEvent["server_message_id"]

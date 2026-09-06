"""容器 HTTP、认证和 WebSocket 端口映射冒烟测试。

使用方法：
    uv run python -m examples.containerSmokeTest
"""

import argparse
import asyncio
import json
import secrets
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import websockets


async def registerAndLogin(
    client: httpx.AsyncClient,
    username: str,
    password: str,
) -> str:
    """注册唯一测试用户并返回短期访问令牌。"""
    registration = await client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    registration.raise_for_status()
    login = await client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )
    login.raise_for_status()
    return str(login.json()["access_token"])


def createWebSocketUrl(baseUrl: str) -> str:
    """从 HTTP 服务地址生成容器端口映射下的 WebSocket 地址。"""
    parsed = urlsplit(baseUrl)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, "/ws", "", ""))


async def runSmokeTest(baseUrl: str) -> None:
    """验证就绪、认证、会话创建及双向 WebSocket 消息。"""
    suffix = secrets.token_hex(6)
    password = f"smoke-password-{secrets.token_hex(8)}"
    async with httpx.AsyncClient(base_url=baseUrl, timeout=5) as client:
        readiness = await client.get("/health/ready")
        readiness.raise_for_status()
        firstToken, secondToken = await asyncio.gather(
            registerAndLogin(client, f"smoke-a-{suffix}", password),
            registerAndLogin(client, f"smoke-b-{suffix}", password),
        )
        secondIdentity = (
            await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {secondToken}"},
            )
        ).json()
        conversationResponse = await client.post(
            "/conversations",
            headers={"Authorization": f"Bearer {firstToken}"},
            json={"peer_id": secondIdentity["user_id"]},
        )
        conversationResponse.raise_for_status()
        conversationId = conversationResponse.json()["conversation_id"]

    websocketUrl = createWebSocketUrl(baseUrl)
    async with websockets.connect(
        websocketUrl,
        additional_headers={"Authorization": f"Bearer {secondToken}"},
    ) as recipientWebSocket:
        async with websockets.connect(
            websocketUrl,
            additional_headers={"Authorization": f"Bearer {firstToken}"},
        ) as senderWebSocket:
            clientMessageId = str(uuid4())
            await senderWebSocket.send(
                json.dumps(
                    {
                        "type": "send_message",
                        "conversation_id": conversationId,
                        "content": "container-smoke-test",
                        "client_message_id": clientMessageId,
                    }
                )
            )
            messageEvent = json.loads(
                await asyncio.wait_for(recipientWebSocket.recv(), timeout=5)
            )
            acceptedEvent = json.loads(
                await asyncio.wait_for(senderWebSocket.recv(), timeout=5)
            )

    if messageEvent["client_message_id"] != clientMessageId:
        raise RuntimeError("接收方消息 ID 与发送命令不一致")
    if messageEvent["recipient_id"] != secondIdentity["user_id"]:
        raise RuntimeError("消息没有路由到会话中的另一名成员")
    if acceptedEvent["server_message_id"] != messageEvent["server_message_id"]:
        raise RuntimeError("持久化确认与实时消息身份不一致")
    print("容器 HTTP、迁移和 WebSocket 冒烟测试通过")


def main() -> None:
    """解析容器映射地址并运行异步冒烟测试。"""
    parser = argparse.ArgumentParser(description="容器端口映射冒烟测试")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="映射到宿主机的 HTTP 服务地址",
    )
    arguments = parser.parse_args()
    asyncio.run(runSmokeTest(arguments.base_url.rstrip("/")))


if __name__ == "__main__":
    main()

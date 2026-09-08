"""Redis 不可用时数据库重连补偿冒烟测试。

运行前应保持两个应用和 PostgreSQL 在线，并暂停 Redis 容器。
"""

import argparse
import asyncio
import json
import secrets
from uuid import uuid4

import httpx
import websockets

from examples.containerSmokeTest import createWebSocketUrl, registerAndLogin


async def runOutageTest(senderBaseUrl: str, recipientBaseUrl: str) -> None:
    """验证 Redis 失败不影响消息提交，接收者仍可从数据库同步。"""
    suffix = secrets.token_hex(6)
    password = f"outage-password-{secrets.token_hex(8)}"
    async with httpx.AsyncClient(base_url=senderBaseUrl, timeout=5) as senderClient:
        firstToken, secondToken = await asyncio.gather(
            registerAndLogin(senderClient, f"outage-a-{suffix}", password),
            registerAndLogin(senderClient, f"outage-b-{suffix}", password),
        )
        secondIdentityResponse = await senderClient.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {secondToken}"},
        )
        secondIdentityResponse.raise_for_status()
        conversationResponse = await senderClient.post(
            "/conversations",
            headers={"Authorization": f"Bearer {firstToken}"},
            json={"peer_id": secondIdentityResponse.json()["user_id"]},
        )
        conversationResponse.raise_for_status()
        conversationId = conversationResponse.json()["conversation_id"]

    async with websockets.connect(
        createWebSocketUrl(senderBaseUrl),
        additional_headers={"Authorization": f"Bearer {firstToken}"},
    ) as senderWebSocket:
        await senderWebSocket.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": conversationId,
                    "content": "saved-while-redis-unavailable",
                    "client_message_id": str(uuid4()),
                }
            )
        )
        acceptedEvent = json.loads(
            await asyncio.wait_for(senderWebSocket.recv(), timeout=5)
        )

    if acceptedEvent["type"] != "accepted" or acceptedEvent["push_status"] != "failed":
        raise RuntimeError("Redis 失败时消息没有保持已提交语义")

    async with websockets.connect(
        createWebSocketUrl(recipientBaseUrl),
        additional_headers={"Authorization": f"Bearer {secondToken}"},
    ) as recipientWebSocket:
        await recipientWebSocket.send(
            json.dumps(
                {
                    "type": "sync_messages",
                    "conversation_id": conversationId,
                    "after_message_id": None,
                    "limit": 100,
                }
            )
        )
        syncResult = json.loads(
            await asyncio.wait_for(recipientWebSocket.recv(), timeout=5)
        )

    contents = [message["content"] for message in syncResult["messages"]]
    if contents != ["saved-while-redis-unavailable"]:
        raise RuntimeError("Redis 失败期间的已提交消息未能从数据库补偿")
    print("Redis 不可用时数据库重连补偿冒烟测试通过")


def main() -> None:
    """解析两个实例地址并运行 Redis 故障冒烟测试。"""
    parser = argparse.ArgumentParser(description="Redis 故障补偿冒烟测试")
    parser.add_argument("--sender-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--recipient-base-url", default="http://127.0.0.1:8001")
    arguments = parser.parse_args()
    asyncio.run(
        runOutageTest(
            arguments.sender_base_url.rstrip("/"),
            arguments.recipient_base_url.rstrip("/"),
        )
    )


if __name__ == "__main__":
    main()

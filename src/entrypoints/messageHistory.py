"""单聊历史消息 HTTP 查询入口和游标编解码。"""

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.application import (
    DEFAULT_HISTORY_PAGE_SIZE,
    MAX_HISTORY_PAGE_SIZE,
    GetMessageHistoryService,
    InvalidMessageHistoryQuery,
    MessageCursor,
    MessageHistoryQuery,
    MessageStorageError,
    UserIdentity,
)
from src.entrypoints.authentication import CurrentUserDependency

CURSOR_VERSION = 1


class HistoryMessageItem(BaseModel):
    """历史消息 HTTP 响应项。"""

    server_message_id: UUID
    client_message_id: UUID
    sender_id: str
    recipient_id: str
    content: str
    created_at: datetime


class MessageHistoryResponse(BaseModel):
    """正向游标分页响应。"""

    messages: list[HistoryMessageItem]
    next_cursor: str | None
    has_more: bool


def encodeHistoryCursor(cursor: MessageCursor) -> str:
    """把应用游标编码为 URL 安全的不透明文本。"""
    payload = json.dumps(
        {
            "version": CURSOR_VERSION,
            "created_at": cursor.created_at.isoformat(),
            "message_id": str(cursor.message_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decodeHistoryCursor(value: str) -> MessageCursor:
    """解码并验证 HTTP 游标。"""
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.b64decode(
                value + padding,
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
        if not isinstance(payload, dict) or payload.get("version") != CURSOR_VERSION:
            raise ValueError("游标版本无效")
        return MessageCursor(
            created_at=datetime.fromisoformat(payload["created_at"]),
            message_id=UUID(payload["message_id"]),
        )
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        raise InvalidMessageHistoryQuery("历史消息游标无效") from error


def createHistoryRouter(
    historyService: GetMessageHistoryService,
    currentUserDependency: CurrentUserDependency,
) -> APIRouter:
    """创建已经注入历史查询服务的 HTTP 路由。"""
    router = APIRouter()

    @router.get("/messages/history", response_model=MessageHistoryResponse)
    async def getMessageHistory(
        peer_id: Annotated[str, Query(min_length=1, max_length=64)],
        currentUser: Annotated[UserIdentity, Depends(currentUserDependency)],
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_HISTORY_PAGE_SIZE),
        ] = DEFAULT_HISTORY_PAGE_SIZE,
        cursor: str | None = None,
    ) -> MessageHistoryResponse:
        """查询两个用户之间按时间正向排列的一页消息。"""
        try:
            decodedCursor = decodeHistoryCursor(cursor) if cursor else None
            page = await historyService.getPage(
                MessageHistoryQuery(
                    user_id=str(currentUser.user_id),
                    peer_id=peer_id,
                    cursor=decodedCursor,
                    limit=limit,
                )
            )
        except InvalidMessageHistoryQuery as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_history_query",
                    "message": str(error),
                },
            ) from error
        except MessageStorageError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "history_storage_failed",
                    "message": "历史消息查询失败",
                },
            ) from error

        return MessageHistoryResponse(
            messages=[
                HistoryMessageItem(
                    server_message_id=message.message_id.value,
                    client_message_id=message.client_message_id.value,
                    sender_id=message.sender_id.value,
                    recipient_id=message.recipient_id.value,
                    content=message.content.value,
                    created_at=message.created_at,
                )
                for message in page.messages
            ],
            next_cursor=(
                encodeHistoryCursor(page.next_cursor) if page.next_cursor else None
            ),
            has_more=page.has_more,
        )

    return router

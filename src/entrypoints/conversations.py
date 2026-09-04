"""一对一会话 HTTP 入口。"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.application import (
    ConversationStorageError,
    ConversationUnavailable,
    CreateConversationCommand,
    CreateConversationService,
    InvalidConversationRequest,
    UserIdentity,
    UserStorageError,
)
from src.entrypoints.authentication import CurrentUserDependency


class CreateConversationPayload(BaseModel):
    """客户端创建或获取单聊会话的请求。"""

    model_config = ConfigDict(extra="forbid")

    peer_id: str = Field(min_length=1, max_length=64)

    @field_validator("peer_id")
    @classmethod
    def validatePeerId(cls, peerId: str) -> str:
        """规范化并拒绝空白成员标识。"""
        normalizedPeerId = peerId.strip()
        if not normalizedPeerId:
            raise ValueError("对方用户 ID 不能为空")
        return normalizedPeerId


class ConversationResponse(BaseModel):
    """一对一会话的公开身份和成员快照。"""

    conversation_id: UUID
    member_ids: list[str]
    created_at: datetime
    created: bool


def createConversationRouter(
    service: CreateConversationService,
    currentUserDependency: CurrentUserDependency,
) -> APIRouter:
    """创建已经注入会话服务和认证依赖的路由。"""
    router = APIRouter()

    @router.post("/conversations", response_model=ConversationResponse)
    async def createOrGetConversation(
        payload: CreateConversationPayload,
        currentUser: Annotated[UserIdentity, Depends(currentUserDependency)],
    ) -> ConversationResponse:
        """为当前用户和指定用户创建或返回唯一单聊会话。"""
        try:
            result = await service.createOrGet(
                CreateConversationCommand(
                    current_user_id=str(currentUser.user_id),
                    peer_id=payload.peer_id,
                )
            )
        except InvalidConversationRequest as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_conversation", "message": str(error)},
            ) from error
        except ConversationUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "conversation_unavailable",
                    "message": "无法创建或访问该会话",
                },
            ) from error
        except (ConversationStorageError, UserStorageError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "conversation_storage_failed",
                    "message": "会话保存失败",
                },
            ) from error

        conversation = result.conversation
        return ConversationResponse(
            conversation_id=conversation.conversation_id.value,
            member_ids=sorted(str(member) for member in conversation.members),
            created_at=conversation.created_at,
            created=result.created,
        )

    return router

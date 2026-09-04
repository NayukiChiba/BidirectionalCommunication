"""创建或获取一对一会话的应用用例。"""

from src.application.authPorts import UserUnitOfWorkFactory
from src.application.conversationModels import (
    CreateConversationCommand,
    CreateConversationResult,
)
from src.application.conversationPorts import ConversationUnitOfWorkFactory
from src.application.exceptions import (
    ConversationStorageConflictError,
    ConversationUnavailable,
    InvalidConversationRequest,
)
from src.domain import Conversation, DomainError, UserId, createConversation


class CreateConversationService:
    """验证用户后以成员组合幂等地创建一对一会话。"""

    def __init__(
        self,
        conversationUnitOfWorkFactory: ConversationUnitOfWorkFactory,
        userUnitOfWorkFactory: UserUnitOfWorkFactory,
    ) -> None:
        """显式接收会话和用户持久化边界。"""
        self._conversationUnitOfWorkFactory = conversationUnitOfWorkFactory
        self._userUnitOfWorkFactory = userUnitOfWorkFactory

    async def createOrGet(
        self,
        command: CreateConversationCommand,
    ) -> CreateConversationResult:
        """返回成员组合对应的唯一会话。"""
        try:
            currentUserId = UserId(command.current_user_id)
            peerId = UserId(command.peer_id)
            conversation = createConversation(currentUserId, peerId)
        except DomainError as error:
            raise InvalidConversationRequest("会话必须包含两名不同用户") from error

        await self._requireUsersExist(currentUserId, peerId)

        existingConversation = await self._getByMembers(currentUserId, peerId)
        if existingConversation is not None:
            return CreateConversationResult(existingConversation, created=False)

        async with self._conversationUnitOfWorkFactory() as unitOfWork:
            await unitOfWork.conversations.add(conversation)
            try:
                await unitOfWork.commit()
            except ConversationStorageConflictError:
                return await self._recoverConcurrentConversation(
                    currentUserId,
                    peerId,
                )
        return CreateConversationResult(conversation, created=True)

    async def _getByMembers(
        self,
        firstMemberId: UserId,
        secondMemberId: UserId,
    ) -> Conversation | None:
        """用独立只读事务查询成员组合，避免 SQLite 读事务升级写锁。"""
        async with self._conversationUnitOfWorkFactory() as unitOfWork:
            return await unitOfWork.conversations.getByMembers(
                firstMemberId,
                secondMemberId,
            )

    async def _requireUsersExist(
        self,
        currentUserId: UserId,
        peerId: UserId,
    ) -> None:
        """拒绝为不存在的用户创建成员关系。"""
        async with self._userUnitOfWorkFactory() as unitOfWork:
            currentUser = await unitOfWork.users.getById(currentUserId)
            peer = await unitOfWork.users.getById(peerId)
        if currentUser is None or peer is None:
            raise ConversationUnavailable("无法创建或访问该会话")

    async def _recoverConcurrentConversation(
        self,
        firstMemberId: UserId,
        secondMemberId: UserId,
    ) -> CreateConversationResult:
        """唯一约束竞态后用新事务读取胜出的会话。"""
        async with self._conversationUnitOfWorkFactory() as unitOfWork:
            conversation = await unitOfWork.conversations.getByMembers(
                firstMemberId,
                secondMemberId,
            )
        if conversation is None:
            raise ConversationStorageConflictError("会话并发创建恢复失败")
        return CreateConversationResult(conversation, created=False)

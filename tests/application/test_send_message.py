"""发送消息应用服务测试。"""

import ast
import inspect
from datetime import datetime, timezone
from types import TracebackType
from uuid import UUID, uuid4

import pytest

import src.application.exceptions as exception_module
import src.application.models as model_module
import src.application.ports as port_module
import src.application.sendMessage as service_module
from src.application import (
    DeliveryOutcome,
    MessageStorageConflictError,
    MessageStorageError,
    SendMessageCommand,
    SendMessageService,
    SendMessageStatus,
)
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    MessageId,
    UserId,
)


class FakeMessageRepository:
    """记录保存调用并可模拟存储异常。"""

    def __init__(
        self,
        events: list[str],
        messages: list[ChatMessage],
        *,
        storageError: BaseException | None = None,
    ) -> None:
        self.messages = messages
        self._events = events
        self._storageError = storageError

    def add(self, message: ChatMessage) -> None:
        """记录消息或抛出预设存储异常。"""
        self._events.append("add")
        if self._storageError is not None:
            raise self._storageError
        self.messages.append(message)

    def getByClientMessageId(
        self,
        senderId: UserId,
        clientMessageId: ClientMessageId,
    ) -> ChatMessage | None:
        """记录幂等查询并返回已经保存的原消息。"""
        self._events.append("get-by-client-id")
        return next(
            (
                message
                for message in self.messages
                if message.sender_id == senderId
                and message.client_message_id == clientMessageId
            ),
            None,
        )


class FakeMessageUnitOfWork:
    """记录事务生命周期并可模拟提交失败。"""

    def __init__(
        self,
        events: list[str],
        persistedMessages: list[ChatMessage],
        *,
        storageError: BaseException | None = None,
        commitError: MessageStorageError | None = None,
    ) -> None:
        self._events = events
        self._commitError = commitError
        self.messages = FakeMessageRepository(
            events,
            persistedMessages,
            storageError=storageError,
        )
        self._snapshot = list(persistedMessages)
        self.committed = False
        self.rolledBack = False

    def __enter__(self) -> "FakeMessageUnitOfWork":
        """记录进入事务范围。"""
        self._events.append("enter")
        return self

    def __exit__(
        self,
        exceptionType: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """异常或未提交时回滚，并记录退出。"""
        if exceptionType is not None or not self.committed:
            self.rollback()
        self._events.append("exit")

    def commit(self) -> None:
        """记录提交或抛出预设提交异常。"""
        self._events.append("commit")
        if self._commitError is not None:
            raise self._commitError
        self.committed = True

    def rollback(self) -> None:
        """记录回滚。"""
        self._events.append("rollback")
        self.messages.messages[:] = self._snapshot
        self.rolledBack = True


class FakeMessageUnitOfWorkFactory:
    """为每次调用创建独立的假工作单元。"""

    def __init__(
        self,
        *,
        storageError: BaseException | None = None,
        commitError: MessageStorageError | None = None,
    ) -> None:
        self.events: list[str] = []
        self._storageError = storageError
        self._commitError = commitError
        self.createdUnits: list[FakeMessageUnitOfWork] = []
        self.persistedMessages: list[ChatMessage] = []

    def __call__(self) -> FakeMessageUnitOfWork:
        """创建并记录工作单元。"""
        unitOfWork = FakeMessageUnitOfWork(
            self.events,
            self.persistedMessages,
            storageError=self._storageError,
            commitError=self._commitError,
        )
        self.createdUnits.append(unitOfWork)
        return unitOfWork


class FakeMessageNotifier:
    """记录通知调用并返回预设结果。"""

    def __init__(self, outcome: DeliveryOutcome, events: list[str]) -> None:
        self.outcome = outcome
        self.messages: list[ChatMessage] = []
        self._events = events

    async def deliver(self, message: ChatMessage) -> DeliveryOutcome:
        """记录消息并返回预设结果。"""
        self._events.append("deliver")
        self.messages.append(message)
        return self.outcome


def makeCommand(
    *,
    senderId: str = "user-a",
    recipientId: str = "user-b",
    content: str = "Hello",
    clientMessageId: UUID | None = None,
) -> SendMessageCommand:
    """创建具有合法默认值的应用命令。"""
    return SendMessageCommand(
        sender_id=senderId,
        recipient_id=recipientId,
        content=content,
        client_message_id=(clientMessageId if clientMessageId is not None else uuid4()),
    )


@pytest.mark.asyncio
async def test_send_message_commits_before_delivering_domain_message() -> None:
    """成功用例应提交消息后再投递同一领域实体。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand(content="  Hello  "))

    unitOfWork = unitOfWorkFactory.createdUnits[0]
    assert result.status is SendMessageStatus.DELIVERED
    assert result.message is not None
    assert result.message.content.value == "Hello"
    assert result.message.message_id.value.version == 4
    assert result.message.created_at.tzinfo is timezone.utc
    assert unitOfWork.messages.messages == [result.message]
    assert unitOfWork.committed is True
    assert unitOfWork.rolledBack is False
    assert notifier.messages == [result.message]
    assert unitOfWorkFactory.events == [
        "enter",
        "get-by-client-id",
        "add",
        "commit",
        "exit",
        "deliver",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deliveryOutcome", "expectedStatus"),
    [
        pytest.param(
            DeliveryOutcome.RECIPIENT_OFFLINE,
            SendMessageStatus.RECIPIENT_OFFLINE,
            id="recipient-offline",
        ),
        pytest.param(
            DeliveryOutcome.FAILED,
            SendMessageStatus.DELIVERY_FAILED,
            id="delivery-failed",
        ),
    ],
)
async def test_send_message_keeps_commit_when_delivery_does_not_succeed(
    deliveryOutcome: DeliveryOutcome,
    expectedStatus: SendMessageStatus,
) -> None:
    """离线或推送失败时应保留已经提交的消息。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory()
    notifier = FakeMessageNotifier(deliveryOutcome, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand())

    unitOfWork = unitOfWorkFactory.createdUnits[0]
    assert result.status is expectedStatus
    assert result.message is not None
    assert unitOfWork.messages.messages == [result.message]
    assert unitOfWork.committed is True
    assert notifier.messages == [result.message]


@pytest.mark.asyncio
async def test_send_message_rolls_back_and_stops_when_repository_fails() -> None:
    """Repository 保存失败时必须回滚且不能通知。"""
    storageError = MessageStorageError("模拟消息保存失败")
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory(storageError=storageError)
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand())

    unitOfWork = unitOfWorkFactory.createdUnits[0]
    assert result.status is SendMessageStatus.STORAGE_FAILED
    assert result.message is not None
    assert unitOfWork.committed is False
    assert unitOfWork.rolledBack is True
    assert notifier.messages == []
    assert unitOfWorkFactory.events == [
        "enter",
        "get-by-client-id",
        "add",
        "rollback",
        "exit",
    ]


@pytest.mark.asyncio
async def test_send_message_rolls_back_and_stops_when_commit_fails() -> None:
    """提交失败时不能返回成功或尝试实时通知。"""
    commitError = MessageStorageError("模拟事务提交失败")
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory(commitError=commitError)
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand())

    unitOfWork = unitOfWorkFactory.createdUnits[0]
    assert result.status is SendMessageStatus.STORAGE_FAILED
    assert result.message is not None
    assert unitOfWork.committed is False
    assert unitOfWork.rolledBack is True
    assert notifier.messages == []
    assert unitOfWorkFactory.events == [
        "enter",
        "get-by-client-id",
        "add",
        "commit",
        "rollback",
        "exit",
    ]


@pytest.mark.asyncio
async def test_unexpected_storage_exception_rolls_back_and_propagates() -> None:
    """未知异常应触发回滚但不能被静默转换。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory(
        storageError=RuntimeError("未知存储异常")
    )
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    with pytest.raises(RuntimeError, match="未知存储异常"):
        await service.send(makeCommand())

    unitOfWork = unitOfWorkFactory.createdUnits[0]
    assert unitOfWork.rolledBack is True
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_send_message_rejects_invalid_domain_input_before_creating_uow() -> None:
    """非法领域输入不能创建工作单元或触发通知。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand(content="   "))

    assert result.status is SendMessageStatus.INVALID_MESSAGE
    assert result.message is None
    assert unitOfWorkFactory.createdUnits == []
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_send_message_allows_same_sender_and_recipient() -> None:
    """应用用例应保留领域允许的自发消息行为。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)

    result = await service.send(makeCommand(senderId="user-a", recipientId="user-a"))

    assert result.status is SendMessageStatus.DELIVERED
    assert result.message is not None
    assert result.message.sender_id == result.message.recipient_id


@pytest.mark.asyncio
async def test_duplicate_command_returns_original_server_message() -> None:
    """重复客户端消息 ID 应返回同一条已提交消息。"""
    unitOfWorkFactory = FakeMessageUnitOfWorkFactory()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, unitOfWorkFactory.events)
    service = SendMessageService(unitOfWorkFactory, notifier)
    command = makeCommand()

    firstResult = await service.send(command)
    secondResult = await service.send(command)

    assert firstResult.status is SendMessageStatus.DELIVERED
    assert secondResult.status is SendMessageStatus.DELIVERED
    assert secondResult.message is firstResult.message
    assert unitOfWorkFactory.persistedMessages == [firstResult.message]
    assert notifier.messages == [firstResult.message, firstResult.message]


@pytest.mark.asyncio
async def test_concurrent_conflict_recovers_original_message() -> None:
    """唯一约束竞态应通过新工作单元读取并返回原消息。"""
    clientMessageId = uuid4()
    originalMessage = ChatMessage(
        message_id=MessageId(uuid4()),
        client_message_id=ClientMessageId(clientMessageId),
        sender_id=UserId("user-a"),
        recipient_id=UserId("user-b"),
        content=MessageContent("Hello"),
        created_at=datetime.now(timezone.utc),
    )
    events: list[str] = []
    unitOfWorks = [
        FakeMessageUnitOfWork(
            events,
            [],
            commitError=MessageStorageConflictError("模拟并发唯一约束冲突"),
        ),
        FakeMessageUnitOfWork(events, [originalMessage]),
    ]

    class ConflictRecoveryFactory:
        """依次返回冲突工作单元和恢复查询工作单元。"""

        def __call__(self) -> FakeMessageUnitOfWork:
            """返回下一个预设工作单元。"""
            return unitOfWorks.pop(0)

    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED, events)
    service = SendMessageService(ConflictRecoveryFactory(), notifier)

    result = await service.send(makeCommand(clientMessageId=clientMessageId))

    assert result.status is SendMessageStatus.DELIVERED
    assert result.message is originalMessage
    assert notifier.messages == [originalMessage]


def test_application_modules_do_not_import_external_frameworks() -> None:
    """应用层不得依赖 Web、传输或数据库框架。"""
    forbiddenModules = {"fastapi", "pydantic", "sqlalchemy", "starlette"}

    for module in (
        exception_module,
        model_module,
        port_module,
        service_module,
    ):
        syntaxTree = ast.parse(inspect.getsource(module))
        importedModules = set()
        for node in ast.walk(syntaxTree):
            if isinstance(node, ast.Import):
                importedModules.update(
                    alias.name.split(".", maxsplit=1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                importedModules.add(node.module.split(".", maxsplit=1)[0])

        assert importedModules.isdisjoint(forbiddenModules)

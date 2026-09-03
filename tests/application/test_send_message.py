"""发送消息应用服务测试。"""

import ast
import inspect
from datetime import timezone
from uuid import uuid4

import pytest

import src.application.exceptions as exception_module
import src.application.models as model_module
import src.application.ports as port_module
import src.application.sendMessage as service_module
from src.application import (
    DeliveryOutcome,
    MessageStorageError,
    SendMessageCommand,
    SendMessageService,
    SendMessageStatus,
)
from src.domain import ChatMessage


class FakeMessageRepository:
    """记录保存调用并可模拟存储失败。"""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.messages: list[ChatMessage] = []
        self.should_fail = should_fail

    def add(self, message: ChatMessage) -> None:
        """记录消息或抛出应用层存储异常。"""
        if self.should_fail:
            raise MessageStorageError("模拟消息保存失败")
        self.messages.append(message)


class FakeMessageNotifier:
    """记录通知调用并返回预设结果。"""

    def __init__(self, outcome: DeliveryOutcome) -> None:
        self.outcome = outcome
        self.messages: list[ChatMessage] = []

    async def deliver(self, message: ChatMessage) -> DeliveryOutcome:
        """记录消息并返回预设结果。"""
        self.messages.append(message)
        return self.outcome


def make_command(
    *,
    sender_id: str = "user-a",
    recipient_id: str = "user-b",
    content: str = "Hello",
) -> SendMessageCommand:
    """创建具有合法默认值的应用命令。"""
    return SendMessageCommand(
        sender_id=sender_id,
        recipient_id=recipient_id,
        content=content,
        client_message_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_send_message_saves_then_delivers_domain_message() -> None:
    """成功用例应创建、保存并投递同一条领域消息。"""
    repository = FakeMessageRepository()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED)
    service = SendMessageService(repository, notifier)

    result = await service.send(make_command(content="  Hello  "))

    assert result.status is SendMessageStatus.DELIVERED
    assert result.message is not None
    assert result.message.content.value == "Hello"
    assert result.message.message_id.value.version == 4
    assert result.message.created_at.tzinfo is timezone.utc
    assert repository.messages == [result.message]
    assert notifier.messages == [result.message]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delivery_outcome", "expected_status"),
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
async def test_send_message_keeps_saved_message_when_delivery_does_not_succeed(
    delivery_outcome: DeliveryOutcome,
    expected_status: SendMessageStatus,
) -> None:
    """离线或推送失败时应保留已经保存的消息并返回明确结果。"""
    repository = FakeMessageRepository()
    notifier = FakeMessageNotifier(delivery_outcome)
    service = SendMessageService(repository, notifier)

    result = await service.send(make_command())

    assert result.status is expected_status
    assert result.message is not None
    assert repository.messages == [result.message]
    assert notifier.messages == [result.message]


@pytest.mark.asyncio
async def test_send_message_does_not_deliver_when_storage_fails() -> None:
    """保存失败时必须停止用例且不能调用通知端口。"""
    repository = FakeMessageRepository(should_fail=True)
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED)
    service = SendMessageService(repository, notifier)

    result = await service.send(make_command())

    assert result.status is SendMessageStatus.STORAGE_FAILED
    assert result.message is not None
    assert repository.messages == []
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_send_message_rejects_invalid_domain_input_before_using_ports() -> None:
    """非法领域输入不能触发保存或通知副作用。"""
    repository = FakeMessageRepository()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED)
    service = SendMessageService(repository, notifier)

    result = await service.send(make_command(content="   "))

    assert result.status is SendMessageStatus.INVALID_MESSAGE
    assert result.message is None
    assert repository.messages == []
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_send_message_allows_same_sender_and_recipient() -> None:
    """应用用例应保留领域允许的自发消息行为。"""
    repository = FakeMessageRepository()
    notifier = FakeMessageNotifier(DeliveryOutcome.DELIVERED)
    service = SendMessageService(repository, notifier)

    result = await service.send(make_command(sender_id="user-a", recipient_id="user-a"))

    assert result.status is SendMessageStatus.DELIVERED
    assert result.message is not None
    assert result.message.sender_id == result.message.recipient_id


def test_application_modules_do_not_import_external_frameworks() -> None:
    """应用层不得依赖 Web、传输或数据库框架。"""
    forbidden_modules = {"fastapi", "pydantic", "sqlalchemy", "starlette"}

    for module in (
        exception_module,
        model_module,
        port_module,
        service_module,
    ):
        syntax_tree = ast.parse(inspect.getsource(module))
        imported_modules = set()
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported_modules.update(
                    alias.name.split(".", maxsplit=1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module.split(".", maxsplit=1)[0])

        assert imported_modules.isdisjoint(forbidden_modules)

"""消息领域模型测试。"""

import ast
import inspect
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

import src.domain.exceptions as exception_module
import src.domain.message as message_module
from src.domain import (
    ChatMessage,
    ClientMessageId,
    InvalidChatMessage,
    InvalidClientMessageId,
    InvalidMessageContent,
    InvalidMessageCreatedAt,
    InvalidMessageId,
    InvalidUserId,
    MessageContent,
    MessageId,
    UserId,
    create_chat_message,
)


def test_user_id_normalizes_value_and_uses_value_equality() -> None:
    """用户标识应规范化空白并按值比较。"""
    user_id = UserId("  user-a  ")

    assert user_id.value == "user-a"
    assert str(user_id) == "user-a"
    assert user_id == UserId("user-a")


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_user_id_rejects_blank_value(value: str) -> None:
    """用户标识规范化后不得为空。"""
    with pytest.raises(InvalidUserId):
        UserId(value)


def test_user_id_rejects_non_string_value() -> None:
    """用户标识必须由字符串创建。"""
    with pytest.raises(InvalidUserId):
        UserId(123)  # type: ignore[arg-type]


def test_user_id_is_immutable() -> None:
    """用户标识创建后不可修改。"""
    user_id = UserId("user-a")

    with pytest.raises(FrozenInstanceError):
        user_id.value = "user-b"  # type: ignore[misc]


def test_message_ids_are_distinct_immutable_value_objects() -> None:
    """服务端和客户端消息标识应保持不同的领域类型。"""
    identifier = uuid4()
    message_id = MessageId(identifier)
    client_message_id = ClientMessageId(identifier)

    assert message_id == MessageId(identifier)
    assert client_message_id == ClientMessageId(identifier)
    assert message_id != client_message_id
    assert str(message_id) == str(identifier)
    assert str(client_message_id) == str(identifier)

    with pytest.raises(FrozenInstanceError):
        message_id.value = uuid4()  # type: ignore[misc]


def test_message_ids_reject_non_uuid_values() -> None:
    """消息标识只能包装已经校验过的 UUID。"""
    with pytest.raises(InvalidMessageId):
        MessageId("not-a-uuid")  # type: ignore[arg-type]

    with pytest.raises(InvalidClientMessageId):
        ClientMessageId("not-a-uuid")  # type: ignore[arg-type]


def test_message_id_generate_returns_uuid4() -> None:
    """服务端消息标识生成入口应使用 UUID4。"""
    message_id = MessageId.generate()

    assert isinstance(message_id.value, UUID)
    assert message_id.value.version == 4


def test_message_content_normalizes_value_and_uses_value_equality() -> None:
    """消息内容应规范化空白并按值比较。"""
    content = MessageContent("  Hello World  ")

    assert content.value == "Hello World"
    assert str(content) == "Hello World"
    assert content == MessageContent("Hello World")


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_message_content_rejects_blank_value(value: str) -> None:
    """消息内容规范化后不得为空。"""
    with pytest.raises(InvalidMessageContent):
        MessageContent(value)


def test_message_content_enforces_normalized_length_limit() -> None:
    """消息内容规范化后的最大长度为 2000 个字符。"""
    assert len(MessageContent("x" * 2000).value) == 2000
    assert len(MessageContent(f"  {'x' * 2000}  ").value) == 2000

    with pytest.raises(InvalidMessageContent):
        MessageContent("x" * 2001)


def test_message_content_is_immutable() -> None:
    """消息内容创建后不可修改。"""
    content = MessageContent("Hello")

    with pytest.raises(FrozenInstanceError):
        content.value = "Changed"  # type: ignore[misc]


def make_chat_message(
    *,
    message_id: MessageId | None = None,
    sender_id: UserId | None = None,
    recipient_id: UserId | None = None,
    content: MessageContent | None = None,
    created_at: datetime | None = None,
) -> ChatMessage:
    """创建包含固定默认值的测试消息。"""
    return ChatMessage(
        message_id=message_id or MessageId(uuid4()),
        client_message_id=ClientMessageId(uuid4()),
        sender_id=sender_id or UserId("user-a"),
        recipient_id=recipient_id or UserId("user-b"),
        content=content or MessageContent("Hello"),
        created_at=created_at or datetime(2026, 8, 6, tzinfo=timezone.utc),
    )


def test_chat_message_uses_message_id_as_entity_identity() -> None:
    """消息实体应只通过服务端消息标识判断身份。"""
    message_id = MessageId(uuid4())
    first_message = make_chat_message(message_id=message_id)
    second_message = ChatMessage(
        message_id=message_id,
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("another-sender"),
        recipient_id=UserId("another-recipient"),
        content=MessageContent("Different content"),
        created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )

    assert first_message == second_message
    assert hash(first_message) == hash(second_message)
    assert first_message != make_chat_message()


def test_chat_message_allows_self_message_and_is_immutable() -> None:
    """消息允许发送给自己，且创建后不可修改。"""
    user_id = UserId("user-a")
    message = make_chat_message(sender_id=user_id, recipient_id=user_id)

    assert message.sender_id == message.recipient_id

    with pytest.raises(FrozenInstanceError):
        message.content = MessageContent("Changed")  # type: ignore[misc]


def test_chat_message_normalizes_aware_time_to_utc() -> None:
    """带时区的创建时间应统一转换为 UTC。"""
    china_timezone = timezone(timedelta(hours=8))
    message = make_chat_message(
        created_at=datetime(2026, 8, 6, 16, tzinfo=china_timezone)
    )

    assert message.created_at == datetime(2026, 8, 6, 8, tzinfo=timezone.utc)
    assert message.created_at.tzinfo is timezone.utc


def test_chat_message_rejects_naive_created_at() -> None:
    """消息创建时间必须包含时区信息。"""
    with pytest.raises(InvalidMessageCreatedAt):
        make_chat_message(created_at=datetime(2026, 8, 6, 8))


def test_chat_message_requires_domain_value_objects() -> None:
    """消息实体只能由合法领域值对象组合。"""
    with pytest.raises(InvalidChatMessage):
        ChatMessage(
            message_id=uuid4(),  # type: ignore[arg-type]
            client_message_id=ClientMessageId(uuid4()),
            sender_id=UserId("user-a"),
            recipient_id=UserId("user-b"),
            content=MessageContent("Hello"),
            created_at=datetime.now(timezone.utc),
        )


def test_create_chat_message_generates_identity_and_utc_time() -> None:
    """消息创建函数应补充服务端身份和 UTC 创建时间。"""
    message = create_chat_message(
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("user-a"),
        recipient_id=UserId("user-b"),
        content=MessageContent("Hello"),
    )

    assert message.message_id.value.version == 4
    assert message.created_at.tzinfo is timezone.utc


def test_domain_modules_do_not_import_frameworks() -> None:
    """领域模块不得依赖传输、Web 框架或数据库框架。"""
    forbidden_modules = {"fastapi", "pydantic", "sqlalchemy", "starlette"}

    for module in (message_module, exception_module):
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

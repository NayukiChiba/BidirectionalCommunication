"""消息存储端口与内存适配器测试。"""

from uuid import uuid4

from src.adapters import InMemoryMessageRepository
from src.application import MessageRepository
from src.domain import (
    ChatMessage,
    ClientMessageId,
    MessageContent,
    UserId,
    create_chat_message,
)


def make_message(content: str = "Hello") -> ChatMessage:
    """创建用于存储测试的聊天消息。"""
    return create_chat_message(
        client_message_id=ClientMessageId(uuid4()),
        sender_id=UserId("user-a"),
        recipient_id=UserId("user-b"),
        content=MessageContent(content),
    )


def use_repository(repository: MessageRepository, message: ChatMessage) -> None:
    """通过应用端口保存消息。"""
    repository.add(message)


def test_add_stores_message_through_application_port() -> None:
    """内存适配器应满足应用层定义的保存需求。"""
    repository = InMemoryMessageRepository()
    message = make_message()

    use_repository(repository, message)

    assert repository.messages == (message,)


def test_messages_returns_snapshot() -> None:
    """读取快照后新增消息不应改变旧快照。"""
    repository = InMemoryMessageRepository()
    first_message = make_message("first")
    second_message = make_message("second")
    repository.add(first_message)

    snapshot = repository.messages
    repository.add(second_message)

    assert snapshot == (first_message,)
    assert repository.messages == (first_message, second_message)


def test_add_keeps_one_record_per_message_identity() -> None:
    """重复保存同一消息实体时不应产生重复存储项。"""
    repository = InMemoryMessageRepository()
    message = make_message()

    repository.add(message)
    repository.add(message)

    assert repository.messages == (message,)

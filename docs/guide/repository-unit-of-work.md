# 消息 Repository 与 Unit of Work

发送消息用例现在通过 Repository 和 Unit of Work 使用 SQLite 持久化，同时保持
Application 和 Domain 不依赖 SQLAlchemy。

## 两个抽象分别解决什么问题

`MessageRepository` 表达应用需要的消息存储能力。目前发送用例只需要：

```python
class MessageRepository(Protocol):
    def add(self, message: ChatMessage) -> None: ...
    def getByClientMessageId(...) -> ChatMessage | None: ...
    def listByConversation(...) -> tuple[ChatMessage, ...]: ...
```

它没有 `save(entity)`、`delete(entity)`、`findAll()` 等通用 CRUD。Repository 的接口
跟随真实用例增长；当前查询只表达幂等键查找和按会话身份查询历史，不暴露通用 ORM
查询。`ConversationRepository` 则以聚合身份和成员组合提供 `getById()`、
`getByMembers()` 和 `add()`。

`MessageUnitOfWork` 表达一次应用操作的原子事务边界：

```python
class MessageUnitOfWork(Protocol):
    messages: MessageRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

实际端口还包含上下文管理器方法，用于保证退出时回滚未提交工作并释放资源。应用层
只能看到这些必要操作，看不到 SQLAlchemy Session 的 `execute()`、`flush()`、
`merge()` 或 ORM 查询接口。

## 为什么注入工作单元工厂

`SendMessageService` 是长生命周期对象，多个 WebSocket 请求可能同时调用它。
AsyncSession 是有状态事务对象，不能让所有 Task 共享同一个实例。因此组合根注入
`MessageUnitOfWorkFactory`，每次 `send()` 只创建一个独立工作单元：

```text
SendMessageService.send
        │
        ├── unitOfWorkFactory() ── 新 UoW / 新 AsyncSession
        │          │
        │          ├── messages.add(message)
        │          └── commit()
        │
        └── notifier.deliver(message)
```

## 事务顺序

发送消息严格遵循：

```text
创建领域消息
    ↓
进入一个 Unit of Work
    ↓
Repository.add
    ↓
UnitOfWork.commit
    ↓ 成功后退出并关闭 AsyncSession
实时推送
```

只有显式 `await commit()` 会保留数据。Repository 只调用 `AsyncSession.add()`，不提交；
否则一个用例涉及多个 Repository 时，第一个 Repository 可能已经提交，后面的操作却
失败，无法作为整体回滚。

提交失败会被数据库适配器转换为 `MessageStorageError`。应用服务返回
`STORAGE_FAILED`，不会调用实时通知端口。未知异常不会静默吞掉，但上下文管理器仍会
先执行回滚和资源释放。

## 为什么先保存再推送

当前顺序保证接收者看到的实时消息已经进入数据库：

- 保存失败：不推送，发送方得到明确的存储失败。
- 保存成功、推送失败：消息仍在数据库中，后续可以通过历史查询或断线补偿恢复。
- 如果先推送后保存：接收者可能已经看到一条最终没有进入数据库的消息，服务端无法
  可靠补偿或解释其身份。

实时推送不是数据库事务的一部分，因此不能承诺“保存和网络发送同时成功”。当前选择
的是可恢复顺序，而不是虚假的跨网络原子性。

## 两种实现

### 内存实现

`InMemoryMessageUnitOfWorkFactory` 为每个用例创建独立暂存区。调用 `commit()` 后才把
消息合并到共享内存状态；未提交退出或异常会清空暂存区。它适合应用层快速单元测试。

### SQLAlchemy 实现

`AsyncSqlAlchemyMessageUnitOfWorkFactory` 保存 AsyncSession 工厂，但不保存 Session。
每次调用创建新的 `AsyncSqlAlchemyMessageUnitOfWork`：

1. `__aenter__()` 创建独立 AsyncSession 和 `AsyncSqlAlchemyMessageRepository`。
2. Repository 把 `ChatMessage` 转换为 `MessageRecord` 并加入 AsyncSession。
3. `await commit()` 提交；数据库异常转换为应用层存储异常。
4. `__aexit__()` 默认异步回滚剩余事务，并始终关闭 AsyncSession。

组合根创建 AsyncEngine 和 AsyncSession 工厂，应用关闭时执行
`await engine.dispose()`。每个 UoW 和并发 Task 都拥有独立 AsyncSession。

## 当前过渡边界

- 运行时数据库访问已使用 AsyncSession，每个用例和 Task 持有独立实例。
- 数据库结构由 Alembic 显式迁移，应用 lifespan 不创建或升级生产表。
- 历史和离线恢复采用正向游标主动拉取，不建立独立离线队列。
- 重复幂等请求返回原消息，但 WebSocket 实时事件仍可能重复投递。

## 测试策略

- 应用单元测试使用假 UoW，验证保存、提交、回滚、提交失败和推送顺序。
- 共同契约测试对内存和 SQLAlchemy 两种实现执行相同的提交与回滚断言。
- SQLAlchemy 集成测试验证唯一约束导致的提交失败会被转换，失败 AsyncSession 被释放，
  后续新 UoW 仍可正常提交。
- WebSocket 外部行为测试为每个测试创建独立 SQLite 文件，验证真实组合链路。

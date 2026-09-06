# 异步 SQLAlchemy

应用运行时数据库访问使用 `AsyncEngine` 和 `AsyncSession`。SQLite 使用 `aiosqlite`，
PostgreSQL 使用 `asyncpg`。业务行为、Repository 语义和 Unit of Work 事务边界保持
不变，等待数据库 I/O 时可以把事件循环执行权交给其他 HTTP 或 WebSocket Task。

## 运行时组件

```text
sqlite+aiosqlite 或 postgresql+asyncpg URL
        ↓
AsyncEngine
        ↓
async_sessionmaker
        ↓ 每次用例调用工厂
AsyncUnitOfWork
        ↓ 独占
AsyncSession
        ↓
AsyncRepository
```

- `createAsyncDatabaseEngine()` 按配置创建应用长期复用的 AsyncEngine。
- `createAsyncSessionFactory()` 创建轻量工厂，并设置 `expire_on_commit=False`。
- `AsyncSqlAlchemyMessageUnitOfWorkFactory` 每次调用返回新的 UoW。
- UoW 在 `__aenter__()` 中创建 AsyncSession，在 `__aexit__()` 中回滚剩余事务并关闭。
- 应用关闭时通过 `await engine.dispose()` 释放异步连接池。

## 一个 Task 一个 AsyncSession

AsyncSession 是一个可变、有状态的事务对象。两个 Task 如果共享它，会同时修改同一份
待写入状态、事务和连接状态，无法确定哪次 flush、commit 或 rollback 属于哪个用例。

当前服务持有的是 UoW 工厂，不持有 Session：

```python
async with unitOfWorkFactory() as unitOfWork:
    await unitOfWork.messages.add(message)
    await unitOfWork.commit()
```

因此每个发送或历史查询 Task 都会取得独立 AsyncSession。并发测试会让两个 Task 同时
进入 UoW、执行查询，并断言 Session 对象不同且退出后全部关闭。

## 显式 I/O

所有可能访问数据库的操作都明确使用 `await`：

```python
result = await session.scalars(statement)
await session.flush()
await session.commit()
await session.rollback()
await session.close()
```

`AsyncSession.add()` 本身只修改内存状态，不产生 I/O，但 Repository 端口仍统一声明为
异步方法，使内存和数据库实现共享一个清晰接口。

当前 `MessageRecord` 没有 relationship，也没有 deferred 字段。Repository 使用
`select(MessageRecord)` 一次加载全部标量字段，并在 Session 活动范围内转换为纯领域
对象；返回 Application 后不会再通过 ORM 属性触发隐式查询。

`expire_on_commit=False` 避免提交后访问 ORM 字段时触发过期刷新。长期代码仍应把 ORM
对象限制在 Repository 内，不依赖这个选项绕过持久化边界。

## 同步版和异步版事务对应关系

```text
同步                           异步
with uow                       async with uow
repository.get(...)            await repository.get(...)
session.scalars(...)            await session.scalars(...)
uow.commit()                    await uow.commit()
uow.rollback()                  await uow.rollback()
engine.dispose()                await engine.dispose()
```

两者仍遵循同一事务语义：只有显式 commit 保留修改，异常或未提交退出默认 rollback，
Repository 不负责提交事务。

## Alembic 为什么仍然同步

Alembic 是应用启动前运行的短生命周期运维命令，不处理并发 WebSocket 请求。SQLite
迁移使用 `sqlite+pysqlite`，PostgreSQL 迁移使用同步 Psycopg；应用运行时分别使用
`aiosqlite` 和 `asyncpg`。同步迁移连接不会进入请求处理链路。

因此“所有运行时数据库路径异步”不等于“禁止任何同步数据库工具”。迁移测试和
`EXPLAIN QUERY PLAN` 结构检查也属于运维/测试边界，不进入 Application 请求链路。

## aiosqlite 没有改变什么

aiosqlite 让等待 SQLite 操作时不阻塞事件循环，但 SQLite 的锁和事务规则没有变化：

- 同一时刻仍然只有一个写事务能够真正修改数据库。
- 慢 SQL、缺失索引和长事务仍然会影响其他请求。
- 异步 API 不会使单条 SQL 自动变快。
- 多实例和高写入吞吐仍需要评估 PostgreSQL 等客户端/服务器数据库。

异步迁移解决的是 Python 服务等待 I/O 的方式，不是数据库存储引擎的并发上限。

PostgreSQL 使用 asyncpg、有界连接池和连接复用前健康检查；其事务隔离与跨方言测试参见
[PostgreSQL 迁移与事务边界](/guide/postgresql)。

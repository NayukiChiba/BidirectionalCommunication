# 关系建模与同步 SQLAlchemy

同步 SQLAlchemy 基础设施已经通过 Repository 与 Unit of Work 接入发送消息用例。
Application 只依赖自有端口，不知道 SQLite、Session 或 ORM 类型。

## 最小消息表

```text
messages
├── message_id         VARCHAR(36)  PRIMARY KEY
├── client_message_id  VARCHAR(36)  NOT NULL
├── sender_id          TEXT         NOT NULL
├── recipient_id       TEXT         NOT NULL
├── content            TEXT         NOT NULL
└── created_at         DATETIME     NOT NULL

UNIQUE (sender_id, client_message_id)
INDEX  (recipient_id, created_at, message_id)
```

### 约束用途

- `message_id` 是服务端生成的消息身份，主键保证每条消息唯一，也支持按 ID 查询。
- `(sender_id, client_message_id)` 保证同一发送者的同一个客户端请求只能保存一次，
  为后续幂等处理提供数据库约束。不同发送者可以使用相同客户端消息 ID。
- 两个 UUID 字段必须是 36 个字符，避免绕过领域转换写入明显错误的标识。
- 发送者和接收者不能是空白字符串。
- 消息正文去除首尾空白后长度必须处于 1 到 2000 之间，与领域规则一致。

目前没有为 `sender_id` 和 `recipient_id` 声明外键。外键必须引用真实存在且生命周期
明确的父表，而项目尚未建立用户持久化模型。为了展示语法而创建空壳用户表会产生错误
的领域承诺；用户表进入项目后，再让这两个字段引用用户主键。

### 索引用途

`(recipient_id, created_at, message_id)` 服务于以下稳定查询：

```sql
SELECT *
FROM messages
WHERE recipient_id = ?
ORDER BY created_at, message_id;
```

`recipient_id` 负责缩小到某个用户收到的消息，`created_at` 用于时间排序，
`message_id` 在创建时间相同时提供稳定次序。主键和唯一约束已经有对应索引，因此没有
再为 `message_id` 或 `(sender_id, client_message_id)` 创建重复索引。

索引会占用磁盘空间，并增加插入、更新和删除的维护成本。因此当前不提前为尚不存在的
查询添加发送者索引或正文索引。

## 代码位置

- `src/config.py`：统一生成项目根目录、数据目录和 SQLite 文件路径。
- `src/adapters/database/connection.py`：创建 Engine、Session 工厂和学习阶段元数据。
- `src/adapters/database/models.py`：声明 `MessageRecord` ORM 持久化模型。
- `src/adapters/database/messageMapper.py`：在领域模型与 ORM 模型之间显式转换。
- `src/adapters/database/sqlAlchemyMessageRepository.py`：使用当前 Session 暂存消息。
- `src/adapters/database/sqlAlchemyMessageUnitOfWork.py`：管理事务和 Session 生命周期。
- `examples/sqlAlchemyExperiment.py`：独立插入、查询和回滚学习示例。

`ChatMessage` 继续是纯 Python 领域实体，不知道 SQLAlchemy。`MessageRecord` 只描述
数据库记录，不承载领域行为。转换位于外层数据库适配器中，因此依赖方向仍然是：

```text
Database Adapter → Domain
Domain           → Python 标准库
```

SQLite 读取 `DATETIME` 时可能不给出时区信息。写入值始终来自已经规范化为 UTC 的领域
对象；映射回领域对象时，转换器会把无时区值显式解释为 UTC，再由领域构造函数验证。

## Engine、Connection 与 Session

- `Engine` 保存数据库 URL、方言和连接池配置，是 Connection 的工厂。本项目通常每个
  数据库创建一个并复用。
- `Connection` 表示一次实际的数据库连接使用过程，可以直接执行 SQL，并持有底层
  事务资源。用完后应关闭，使资源返回连接池。
- `Session` 是 ORM 的工作区和事务边界。它从 Engine 取得 Connection，跟踪 ORM
  对象变化，维护身份映射，并在刷新时生成 SQL。Session 应按一次工作单元创建，不能
  当作全局对象长期共享。

## flush、commit、rollback 与 close

- `flush()` 把 Session 中待处理的变化转换成 SQL，写入当前事务，但事务仍可回滚。
- `commit()` 会先刷新，再提交事务。提交后，新 Session 才能稳定查询到数据。
- `rollback()` 撤销当前事务。即使已经 `flush()`，回滚后新 Session 也查不到该记录。
- `close()` 释放 Session 持有的连接和 ORM 对象；未提交事务会被回滚。

Session 工厂保留 `autoflush=True` 和 `expire_on_commit=True` 的默认语义。提交后对象
属性会过期；关闭 Session 后不要继续把 ORM 对象当作可自由访问的领域对象使用。

## 运行独立实验

```bash
uv run python -m examples.sqlAlchemyExperiment
```

默认数据库文件为 `data/chat.sqlite3`，路径由 `src/config.py` 统一生成。也可以指定临时
路径：

```bash
uv run python -m examples.sqlAlchemyExperiment \
  --database-path ./tmp/sqlalchemy-learning.sqlite3
```

实验会输出 SQL，并依次验证：

1. `add()` 后显式 `flush()` 生成 INSERT。
2. `commit()` 后关闭原 Session。
3. 新 Session 使用 SQLAlchemy 2.x 的 `select()` 查询到消息。
4. 另一条消息在 `flush()` 后执行 `rollback()`。
5. 再创建一个 Session，确认回滚消息不存在。

数据库结构已经交给 Alembic 版本化管理。应用、学习实验和自动化测试都必须先执行
迁移，不再调用 `DatabaseBase.metadata.create_all()`。

## 为什么先使用同步 Session

同步和异步 SQLAlchemy 共享 ORM、SQL、事务与 Session 工作单元等核心概念。当前先用
同步 API，可以让执行顺序和事务边界保持直观，避免同时引入协程调度、异步驱动和
`AsyncSession` 生命周期。理解同步事务后，Issue 16 再迁移异步访问。

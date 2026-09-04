# 关系建模与 SQLAlchemy

异步 SQLAlchemy 基础设施已经通过 Repository 与 Unit of Work 接入发送消息用例。
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
INDEX  (sender_id, recipient_id, created_at, message_id)
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

`(sender_id, recipient_id, created_at, message_id)` 服务于双向单聊查询：

```sql
SELECT *
FROM messages
WHERE (sender_id = ? AND recipient_id = ?)
   OR (sender_id = ? AND recipient_id = ?)
ORDER BY created_at, message_id;
```

两个方向都对 `sender_id` 和 `recipient_id` 使用等值条件，可以复用同一个索引；
`created_at` 用于时间排序，`message_id` 在创建时间相同时提供稳定次序。主键和唯一
约束已经有对应索引，因此不创建重复索引。

索引会占用磁盘空间，并增加插入、更新和删除的维护成本。因此当前不提前为尚不存在的
查询添加发送者索引或正文索引。

## 用户表

认证用户使用独立 `users` 表保存稳定 UUID、规范化唯一用户名、Argon2id 密码哈希和
UTC 创建时间。数据库没有明文密码字段；用户表暂不与消息表建立外键，避免在加入会话
成员模型前改变已有消息数据语义。

## 代码位置

- `src/config.py`：统一生成项目根目录、数据目录和 SQLite 文件路径。
- `src/adapters/database/connection.py`：创建 AsyncEngine 和 AsyncSession 工厂。
- `src/adapters/database/models.py`：声明 `MessageRecord` ORM 持久化模型。
- `src/adapters/database/userMapper.py`：转换用户领域实体与用户 ORM 记录。
- `src/adapters/database/messageMapper.py`：在领域模型与 ORM 模型之间显式转换。
- `src/adapters/database/asyncSqlAlchemyMessageRepository.py`：执行异步消息持久化查询。
- `src/adapters/database/asyncSqlAlchemyMessageUnitOfWork.py`：管理异步事务和 Session。
- `examples/sqlAlchemyExperiment.py`：独立插入、查询和回滚学习示例。

`ChatMessage` 继续是纯 Python 领域实体，不知道 SQLAlchemy。`MessageRecord` 只描述
数据库记录，不承载领域行为。转换位于外层数据库适配器中，因此依赖方向仍然是：

```text
Database Adapter → Domain
Domain           → Python 标准库
```

SQLite 读取 `DATETIME` 时可能不给出时区信息。写入值始终来自已经规范化为 UTC 的领域
对象；映射回领域对象时，转换器会把无时区值显式解释为 UTC，再由领域构造函数验证。

## AsyncEngine、AsyncConnection 与 AsyncSession

- `AsyncEngine` 保存异步数据库 URL、方言和连接池配置，是 AsyncConnection 的工厂。
- `AsyncConnection` 表示一次异步数据库连接使用过程，用完后应异步关闭。
- `AsyncSession` 是 ORM 工作区和事务边界。它从 AsyncEngine 取得连接，跟踪 ORM
  对象变化，并在刷新时生成 SQL。每个并发 Task 必须使用独立 AsyncSession。

## flush、commit、rollback 与 close

- `await flush()` 把待处理变化转换成 SQL，写入当前事务，但仍可回滚。
- `await commit()` 会先刷新，再提交事务。
- `await rollback()` 撤销当前事务。
- `await close()` 释放 AsyncSession 持有的连接和 ORM 对象。

AsyncSession 工厂设置 `expire_on_commit=False`，防止提交后属性访问隐式触发数据库
刷新。ORM 记录仍然只在 Repository 内使用，外层取得的是纯领域对象。

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

1. `add()` 后显式 `await flush()` 生成 INSERT。
2. `await commit()` 后关闭原 AsyncSession。
3. 新 AsyncSession 使用 SQLAlchemy 2.x 的 `select()` 查询到消息。
4. 另一条消息在 `await flush()` 后执行 `await rollback()`。
5. 再创建一个 AsyncSession，确认回滚消息不存在。

数据库结构已经交给 Alembic 版本化管理。应用、学习实验和自动化测试都必须先执行
迁移，不再调用 `DatabaseBase.metadata.create_all()`。

## 从同步 Session 迁移到异步

项目先用同步 Session 学习 ORM 和事务，再在不改变业务语义的情况下迁移到
AsyncSession。完整并发和隐式 I/O 边界参见[异步 SQLAlchemy](/guide/async-sqlalchemy)。

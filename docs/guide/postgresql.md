# PostgreSQL 迁移与事务边界

PostgreSQL 是独立数据库服务，多个应用进程通过网络连接共享事务和锁；SQLite 则把
数据库放在应用主机的单个文件中。当前实现通过基础设施层的数据库 URL 切换后端，
Domain、Application、Repository 端口和用例代码没有数据库方言分支。

## SQLite 专属假设清单

迁移前存在的假设及处理如下：

| SQLite 假设 | 当前处理 |
| --- | --- |
| 数据库由 `pathlib` 文件路径定位 | 新增 `DATABASE_URL`；路径仅作为 SQLite 兼容入口 |
| 运行时固定 `sqlite+aiosqlite` | PostgreSQL 运行时改用 `postgresql+asyncpg` |
| Alembic 固定 `sqlite+pysqlite` | PostgreSQL 迁移 URL转换为同步 `postgresql+psycopg` |
| 每条连接执行 `PRAGMA foreign_keys=ON` | 仅保留在 SQLite 数据库适配器分支 |
| Alembic 始终 `render_as_batch=True` | 仅 SQLite 使用 batch，PostgreSQL 使用原生 ALTER |
| SQLite `DATETIME` 可能返回无时区值 | 映射器继续兼容；PostgreSQL 使用 `TIMESTAMP WITH TIME ZONE` |
| `EXPLAIN QUERY PLAN` 和临时数据库文件 | 保留为 SQLite 专项测试；PostgreSQL 单独检查索引和分页 |
| 单文件复制就是备份 | PostgreSQL 改用 `pg_dump`/`pg_restore` |
| SQLite 同时只有一个写事务 | PostgreSQL 允许多个事务并发，通过行锁和 MVCC 协调 |

方言判断只存在于 `src/adapters/database/` 和 Alembic 环境，Application 不知道当前使用
哪个数据库。

## 驱动职责

- `asyncpg`：应用运行时的异步 SQLAlchemy 驱动，兼容 Windows 和 Linux 事件循环。
- `psycopg[binary]`：Alembic 短生命周期同步迁移连接。
- SQLAlchemy `AsyncEngine`：持有有界连接池并为每个 AsyncSession 提供连接。

配置示例：

```dotenv
DATABASE_URL=postgresql+asyncpg://chat:<password>@127.0.0.1:5432/chat
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_POOL_RECYCLE_SECONDS=1800
```

数据库 URL 使用 `SecretStr` 保存，不进入配置 `repr` 或结构化日志。

连接池常驻连接默认 5 个，短时最多额外创建 10 个；取连接最多等待 30 秒，连接使用
1800 秒后回收。`pool_pre_ping=True` 会在复用连接前检查连接是否仍然有效。连接池容量
必须结合 PostgreSQL `max_connections`、应用实例数和后台任务数量统一计算，不能让每个
实例无限扩张。

## 事务和数据类型验证

真实 PostgreSQL 测试确认：

- 默认隔离级别是 `READ COMMITTED`。
- 一个事务不能看到另一个尚未提交事务的数据。
- `DateTime(timezone=True)` 映射为 `TIMESTAMP WITH TIME ZONE`，领域边界统一返回 UTC。
- `(sender_id, client_message_id)` 唯一约束在并发提交时只接受一条消息。
- `member_pair_key` 唯一约束在并发反向创建时只接受一个会话。
- `(conversation_id, created_at, message_id)` 索引存在，相同时间消息继续按唯一消息 ID
  稳定分页。

当前 UUID 仍以 36 字符字符串保存，而不是立即改为 PostgreSQL 专属 UUID 类型。这能
保持已有迁移和 SQLite 契约一致；若未来切换原生 UUID，应单独编写数据迁移并验证排序。

## 开发数据库和测试

启动 PostgreSQL：

```bash
docker compose up -d postgres --wait
```

PowerShell 中运行 PostgreSQL 专项测试：

```powershell
$env:TEST_POSTGRES_URL = `
  "postgresql+asyncpg://chat:<password>@127.0.0.1:5432/chat"
uv run pytest tests/adapters/database/test_postgresql.py -v
```

该测试会把指定数据库降级到 `base`、重新升级到 `head`，最后再次降级，只能指向专门
测试数据库，绝不能指向开发或生产数据。没有 `TEST_POSTGRES_URL` 时本地完整测试会
明确跳过 PostgreSQL 模块；CI 提供独立 PostgreSQL service，因此六项测试必须通过。

## 空库迁移

本机运行：

```bash
uv run alembic upgrade head
uv run alembic check
```

或显式覆盖 URL：

```bash
uv run alembic -x database_url=<postgresql-url> upgrade head
```

全部已有 revision 可以在空 PostgreSQL 18 数据库执行。Alembic 只迁移结构，不会自动
复制现有 SQLite 业务数据。

## SQLite 数据迁移演练

生产切换前按以下顺序在预演环境执行：

1. 记录当前 SQLite Alembic revision、文件大小和各表行数。
2. 停止应用写入，复制 `data/chat.sqlite3` 到只读备份位置并计算 SHA-256。
3. 对目标 PostgreSQL 执行 `alembic upgrade head`。
4. 使用独立迁移程序按 `users → conversations → conversation_members → messages` 顺序
   读取 SQLite 并批量写入 PostgreSQL；成员先以空进度写入，消息导入完成后再补写
   送达/已读消息引用。
5. 每批事务失败时整体回滚，不跳过约束错误。
6. 对比每张表行数、主键集合、外键、唯一约束、UTC 时间和随机消息样本。
7. 在隔离环境运行认证、历史分页、幂等、确认和重连冒烟测试。
8. 再次停止写入，执行最终增量或重新全量导入，随后切换应用 `DATABASE_URL`。
9. 保留原 SQLite 文件为只读回滚源，经过观察窗口后再决定归档。

仓库当前没有自动 SQLite→PostgreSQL 数据搬运脚本，因此不能把“空库迁移测试通过”
描述成“已有数据已经安全迁移”。

## PostgreSQL 备份与恢复演练

迁移或升级前创建自包含格式备份：

```bash
docker compose exec postgres \
  pg_dump -U chat -d chat --format=custom --file=/tmp/chat-before-change.dump
docker cp <postgres-container>:/tmp/chat-before-change.dump ./backups/
```

不要直接覆盖当前数据库验证备份。创建新的恢复数据库后执行：

```bash
docker compose exec postgres createdb -U chat chat_restore
docker compose exec postgres \
  pg_restore -U chat -d chat_restore --clean --if-exists \
  /tmp/chat-before-change.dump
```

然后把测试应用临时指向 `chat_restore`，运行 `/health/ready` 和核心冒烟测试，并核对
行数与 revision。

## 失败回滚

如果结构迁移或数据导入失败：

1. 不启动新版本应用，保持旧实例和旧数据库不变。
2. 保存迁移日志和失败数据库用于分析，不在原库反复尝试破坏性降级。
3. 从已验证备份恢复到一个新数据库，而不是覆盖唯一可用副本。
4. 将 `DATABASE_URL` 切回旧 SQLite 或已恢复 PostgreSQL，启动上一应用版本。
5. 等 `/health/ready` 成功并完成登录、历史和发送冒烟测试后恢复流量。

Alembic downgrade 只能回退已明确验证为可逆的结构变化，不能替代数据备份。

## 当前仍未解决的限制

PostgreSQL 解决数据库文件不能跨主机共享、SQLite 单写者和连接容量管理问题，也更接近
生产事务行为。但 WebSocket 在线连接表仍在单个进程内，跨实例实时投递尚未实现；在
完成共享在线状态和跨实例路由前，Compose 仍只启动一个应用副本。

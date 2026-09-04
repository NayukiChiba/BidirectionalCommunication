# Alembic 数据库迁移

Alembic 迁移现在是数据库结构的唯一版本化历史。ORM 模型描述应用当前期望的结构，
迁移脚本描述数据库如何从一个已知版本逐步变化到另一个版本；修改 ORM 类不会自动
改变已有数据库。

## 目录结构

```text
alembic.ini
pyproject.toml
migrations/
├── env.py
├── script.py.mako
└── versions/
    ├── e5f06ff274b9_create_messages_table.py
    ├── b5db92390df6_add_conversation_history_indexes.py
    └── f53ad4a832a9_create_users_table.py
```

- `pyproject.toml` 保存迁移目录和项目导入路径。
- `alembic.ini` 只保存 Alembic 日志配置，并保持 ASCII，避免 Windows 区域编码问题。
- `migrations/env.py` 加载 `DatabaseBase.metadata`，并从 `src.config` 取得默认数据库
  路径。
- `migrations/versions/` 保存按 `down_revision` 串联的迁移历史。
- `alembic_version` 表记录某个数据库当前已经执行到的 revision。

迁移环境不导入 `main.py`、Bootstrap 或 FastAPI，也不需要运行 Web 服务。

## 首个迁移

revision `e5f06ff274b9` 创建：

- `messages` 表及六个字段。
- 服务端消息 ID 主键。
- 发送者与客户端消息 ID 联合唯一约束。
- UUID 长度、非空白用户 ID 和正文长度检查约束。
- `(recipient_id, created_at, message_id)` 收件箱查询索引。

`downgrade()` 按相反顺序删除索引和消息表。

revision `b5db92390df6` 将旧收件人索引替换为与双向单聊游标查询匹配的
`(sender_id, recipient_id, created_at, message_id)` 复合索引。

revision `f53ad4a832a9` 创建认证用户表，只保存规范化用户名和 Argon2id 密码哈希。

该文件最初由 `--autogenerate` 生成，随后进行了人工审查：保留与 ORM 元数据一致的
字段类型和约束，确认索引用途，移除生成器提示，并把初始建表整理为直接、可读的
`op.create_table()` 和 `op.create_index()`。

## 开发与部署流程

首次启动或拉取新迁移后，先升级数据库：

```bash
uv sync --dev
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

应用启动不会运行迁移，也不会调用 `metadata.create_all()`。缺少迁移时，健康检查仍可
启动，但消息写入会返回存储失败。

查看迁移状态：

```bash
uv run alembic current
uv run alembic history --verbose
uv run alembic heads
```

降级一版和重新升级：

```bash
uv run alembic downgrade -1
uv run alembic upgrade head
```

降级可能删除表或数据，执行前必须确认目标数据库和迁移脚本。本项目的首个迁移降到
`base` 会删除整个消息表。

## 创建后续迁移

先修改 ORM 映射，再生成候选迁移：

```bash
uv run alembic revision --autogenerate -m "说明结构变化"
```

生成后必须人工检查：

1. revision 和 `down_revision` 是否连接正确。
2. `upgrade()` 是否只包含预期变化。
3. `downgrade()` 是否能够安全恢复上一结构。
4. 字段类型、可空性、默认值、约束名称和索引是否正确。
5. 数据迁移、重命名和 SQLite 表重建是否需要手工代码。

最后检查 ORM 元数据和 head 是否一致：

```bash
uv run alembic check
```

自动生成只是比较数据库与元数据，并不知道业务语义。例如，它可能把字段重命名识别为
“删除旧字段并新增字段”，从而丢失数据；数据回填、约束收紧顺序和部署兼容性也需要
开发者决定。

## 隔离数据库

自动化测试通过 `createMigrationConfig()` 把 Alembic 指向 pytest 的临时 SQLite 文件，
每个测试独立升级，不访问 `data/chat.sqlite3`。命令行实验也可以覆盖路径：

```bash
uv run alembic \
  -x database_path=./tmp/migration-test.sqlite3 \
  upgrade head
```

路径通过 `pathlib` 和 SQLAlchemy `URL.create()` 处理，不依赖字符串拼接。

## SQLite WAL 决策

当前没有启用 WAL，也没有执行 `PRAGMA journal_mode=WAL`。现阶段是单进程学习项目，
缺少需要读写并发优化的真实负载，保持默认日志模式更简单。

WAL 允许读取者和写入者更好地并行，并通常减少同步写入成本，但 SQLite 仍然同时只有
一个写入者。WAL 还会产生 `-wal` 和 `-shm` 文件，需要检查点和同机共享内存支持，
不能把 SQLite 变成多写数据库。如果以后启用，必须在连接建立时显式执行 PRAGMA，
读取返回值确认实际模式，并增加集成测试。

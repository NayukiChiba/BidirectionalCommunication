# 测试层级与数据库后端

| 层级 | 位置 | 职责 |
| --- | --- | --- |
| 领域单元测试 | `tests/domain/` | 值对象、实体、聚合与位置不变量 |
| 应用单元测试 | `tests/application/` | 用假端口验证用例编排和失败路径 |
| 适配器/契约测试 | `tests/adapters/` | 连接、限流、通知和 Repository 契约 |
| 数据库集成测试 | `tests/adapters/database/` | SQLite/PostgreSQL 迁移、约束和并发事务 |
| 接口与端到端测试 | `tests/test_*.py` | HTTP、WebSocket 和完整对象图 |

默认测试使用临时 SQLite 文件，速度快且彼此隔离。设置 `TEST_POSTGRES_URL` 后还会执行
真实 PostgreSQL 专项测试，验证空库迁移、时区、分页、事务隔离和并发唯一约束：

```powershell
$env:TEST_POSTGRES_URL = `
  "postgresql+asyncpg://chat:<password>@127.0.0.1:5432/chat_test"
uv run pytest
```

PostgreSQL fixture 会在模块开始和结束时把目标数据库降级到 `base`。该 URL 只能指向
隔离测试数据库，禁止使用开发或生产数据库。

并发和时间测试不使用固定 `sleep`：限流器注入测试时钟，并发事务使用
`asyncio.gather()`/事件协调，WebSocket 测试等待明确协议事件。

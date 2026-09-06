# 质量、可观测性与安全基线

本基线面向单实例聊天服务，目标是能够持续验证、限制明显资源滥用、关联故障流程并
安全关闭。它不是企业级监控平台，也不替代反向代理、容器编排和主机安全配置。

## 测试层级

测试职责记录在 `tests/README.md`：

- 领域单元测试保护值对象、聚合和累计位置不变量。
- 应用单元测试通过假端口验证用例编排和失败路径。
- 适配器测试保护连接、限流、转换和共同端口契约。
- 数据库集成测试运行真实 SQLite 和 PostgreSQL，验证迁移、约束和并发事务。
- 根目录接口测试通过 TestClient 覆盖完整 HTTP/WebSocket 用户故事。

并发连接、并发消息幂等、并发位置推进和重连补偿都有自动化测试。时间相关测试通过
注入单调时钟或等待明确事件推进，不使用固定 `sleep` 猜测异步操作完成时间。

## 环境配置

认证密钥仍是必填配置；缺失或短于 32 字节时应用在启动阶段失败。单实例限制通过同一
`.env` 读取：

```dotenv
AUTH_SECRET_KEY=<至少32字节随机值>
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=15
DATABASE_URL=postgresql+asyncpg://chat:<password>@127.0.0.1:5432/chat
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
WS_MAX_MESSAGE_BYTES=16384
WS_INPUT_RATE_LIMIT_COUNT=30
WS_INPUT_RATE_LIMIT_WINDOW_SECONDS=10
WS_MAX_CONNECTIONS=1000
READINESS_TIMEOUT_SECONDS=1
LOG_LEVEL=INFO
```

数值超出代码声明的安全范围、日志级别不受支持或认证密钥缺失时，Pydantic Settings
会给出明确校验错误，不会带着危险默认值继续运行。

## WebSocket 资源限制

- 单条文本命令默认最多 16 KiB，按 UTF-8 字节数计算。超限返回
  `message_too_large`，随后以 `4409` 关闭连接。
- 每个连接默认 10 秒最多输入 30 条命令。超限返回 `rate_limited`，随后以 `4408`
  关闭连接。
- 单实例默认最多登记 1000 个不同用户连接。容量满时以 `4429` 拒绝新用户；同一用户
  的替换连接不额外占用容量。
- 正文、用户名、密码、分页大小、UUID 和多余字段继续由 Pydantic 与领域模型限制。

应用层字节检查发生在 ASGI 收到文本之后。生产启动还应把服务器帧上限设置为相同或更
小的值，使超大帧在进入应用前被拒绝：

```bash
uv run uvicorn main:app --ws-max-size 16384
```

限流状态只在当前连接和当前进程内维护。多实例全局限流需要共享状态，属于后续扩展。

## 认证与权限响应

- HTTP 缺少、过期或非法 Bearer 凭证统一返回 `401` 和“无法验证身份凭证”。
- WebSocket 缺少或非法凭证统一使用关闭码 `4401` 和同一原因。
- 会话不存在和当前用户不是成员统一返回 `conversation_unavailable`，不暴露会话存在
  性。
- 确认位置中的成员身份只取自 JWT，客户端不能指定另一个成员。

内部日志可以记录“认证拒绝”或“权限拒绝”事件，但不会记录完整令牌、密码和私聊正文。

## 结构化日志

应用日志输出单行 JSON，固定字段包括：

```text
timestamp, level, logger, message, event,
request_id / connection_id, user_id, conversation_id,
client_message_id, server_message_id, status, duration_ms
```

HTTP 响应返回服务端生成的 `X-Request-ID`。每个 WebSocket 连接生成一个
`connection_id`，连接建立、消息接受、拒绝和断开使用同一个 ID。日志格式化器只允许
固定安全上下文字段，不输出请求正文、密码、完整访问令牌或私聊正文；异常只记录类型，
避免未知异常文本意外包含敏感数据。

日志、指标和追踪回答的问题不同：

- 日志回答某一次请求或连接发生了什么。
- 指标回答一段时间内错误率、连接数和延迟是否异常。
- 追踪回答一次调用跨组件或服务经过了哪些步骤。

当前单体只落地结构化日志和可由日志聚合的状态字段，不提前引入指标后端或分布式追踪
SDK。进入多实例或出现真实告警需求后再增加。

## 存活与就绪

```http
GET /health/live
GET /health/ready
```

- 存活检查不访问数据库，只判断事件循环能否响应；失败时编排系统可以重启进程。
- 就绪检查在短超时内查询 `alembic_version`，同时验证数据库可连接且迁移版本与应用
  匹配；失败时返回 `503`，负载均衡器应停止向该实例发送业务流量，但不必立即重启。
- `/health` 保留为低成本存活检查别名。

## 优雅关闭

FastAPI lifespan 关闭顺序固定为：

```text
停止登记新 WebSocket
→ 使用 1001 关闭现有连接
→ 清空单进程连接表
→ dispose AsyncEngine 连接池
```

单个连接关闭失败会记录异常类型并继续清理其他连接；业务入口的未知顶层异常不会被
静默吞掉。

## 依赖漏洞审计

2026-09-06 执行：

```bash
uvx pip-audit . --progress-spinner off --strict
```

结果为 `No known vulnerabilities found`。这是基于当时漏洞数据库的时间点结论，不是
永久安全证明。新增的 GitHub Actions `dependency-audit` job 会在 push 和 pull request
时重新安装项目运行时依赖并执行 `pip-audit`，发现已知漏洞时使检查失败。

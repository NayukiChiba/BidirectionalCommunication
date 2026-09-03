# BidirectionalCommunication

一个基于 Python 和 FastAPI 构建的双向通信学习项目。

## 安装与启动

```bash
uv sync --dev
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

`main.py` 是唯一程序启动入口，FastAPI 应用由 `bootstrap.create_app()` 完成组装。

运行检查：

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

项目文档使用 VitePress 构建：

```bash
cd docs
npm install
npm run dev
```

项目以 WebSocket 私聊为主线，逐步学习和实践：

- HTTP 与 WebSocket 通信。
- Python 异步编程。
- 在线连接与消息协议管理。
- 面向对象设计与洋葱架构。
- SQLAlchemy 数据持久化。
- 历史消息游标分页、离线主动拉取和发送幂等。
- 用户认证、消息可靠性和自动化测试。

## 第一版目标

- 两个用户连接同一台服务器。
- 用户之间可以实时发送和接收文字消息。
- 使用内存维护单进程在线连接。
- 提供基础健康检查和自动化测试。

第一版不包含数据库、登录注册、群聊、文件传输、语音、视频和完整客户端界面。
后续将在核心通信流程稳定后逐步增加持久化、身份认证和可靠投递能力。

## 项目结构

```text
src/
├── domain/         消息领域对象、不变量和领域异常
├── application/    发送消息用例、命令、结果和端口
├── adapters/       内存、WebSocket 和异步数据库适配器
└── entrypoints/    FastAPI 路由、Pydantic 协议模型和错误映射
bootstrap.py        唯一组合根，创建并注入具体依赖
main.py             唯一程序启动入口
examples/           可独立运行的学习示例
migrations/         Alembic 数据库迁移环境和版本历史
tests/              领域、应用、适配器、架构和外部行为测试
docs/               VitePress 项目文档
```

依赖只能由外向内：

```text
main → bootstrap → entrypoints / adapters → application → domain
```

- Domain 只依赖 Python 标准库和自身模块。
- Application 只依赖 Domain 和自身定义的端口。
- Adapters 使用 SQLAlchemy、内存实现和 WebSocket 实现 Application 端口。
- Entrypoints 将外部协议转换为 Application 命令和响应。
- Bootstrap 是唯一知道所有具体实现并负责生命周期的模块。
- Main 只调用组合根并暴露 `app`。

## WebSocket 连接策略

- 同一用户重复登录时采用“最后建立的连接优先”规则。新连接登记成功后，旧连接以
  `4001` 关闭，原因固定为“该账号已在其他连接登录”。这是决定哪个客户端代表用户
  在线的业务规则，而不是 WebSocket 协议本身的要求。
- 服务停止时，所有当前连接以标准关闭码 `1001` 关闭，原因固定为“服务停止”。单个
  连接关闭失败不会阻止其他连接清理，连接表最终会被清空。
- 旧连接晚于新连接退出时，管理器会比较连接对象身份，因此旧连接不会误删新连接。
  对应的交错测试为 `test_replaced_connection_cannot_remove_current_connection`。
- 当前没有空闲超时、代理断链检测或在线状态时效需求，因此不增加应用级心跳。
  WebSocket 协议级 Ping/Pong 由服务器实现负责，不与业务消息混用。
- 在线表仅服务单进程，事件循环内的连接登记操作不跨线程，也不跨进程，所以当前不
  需要 Redis 或锁。扩展到多进程或多实例时，才需要引入共享在线状态与跨实例投递。

## 当前限制

- 只支持单进程在线连接和单文件 SQLite 消息存储。
- 没有身份认证，客户端可以自行指定 `user_id`。
- 进程退出后在线状态会丢失，消息会保存在 `data/chat.sqlite3`。
- 应用运行时使用 AsyncSession 和 aiosqlite；Alembic 运维命令仍使用同步连接。
- 应用不会自动迁移数据库，部署或拉取新版本后需要执行 `alembic upgrade head`。
- 离线消息需要客户端主动拉取，尚未实现服务端自动补发。
- 没有送达状态、已读回执或跨实例通信。
- ACK 只表示服务端已向目标 WebSocket 执行发送，不表示用户已经阅读。

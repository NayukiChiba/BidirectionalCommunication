# BidirectionalCommunication

一个基于 Python 和 FastAPI 构建的双向通信学习项目。

## 开箱即用启动

只需要 Python 3.11 或更高版本，不需要 Docker、PostgreSQL 或 Redis：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe main.py
```

也可以使用 uv：

```bash
uv sync --dev
uv run python main.py
```

`python main.py` 固定使用单机模式：自动生成认证密钥、自动迁移
`data/chat.sqlite3`，默认监听 `127.0.0.1:8000`，并且不连接 Redis。可以通过环境变量
`APP_HOST` 和 `APP_PORT` 修改监听地址。FastAPI 应用仍由 `bootstrap.create_app()` 完成
组装。

如需使用外部 PostgreSQL 或可选 Redis，复制并编辑 `.env.example`，执行显式迁移后用
Uvicorn 启动：

```powershell
Copy-Item .env.example .env
uv run alembic upgrade head
uv run uvicorn main:app --reload --ws-max-size 16384
```

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

## 桌面客户端

`desktop/` 提供使用 Rust、Tauri 2 和 Vue 3 构建的桌面聊天客户端。每个 Release 同时
提供两个版本：

- `双向通信_0.5_x64-setup.exe`：内置由 PyInstaller 打包的 FastAPI sidecar 和
  SQLite，最终用户不需要安装 Python、Docker、PostgreSQL 或 Redis。
- `双向通信客户端_0.5_x64-setup.exe`：不包含后端，适合连接团队部署的远程服务。

桌面开发环境需要先准备 Python 和 Node.js 依赖：

```bash
uv sync --dev
cd desktop
npm install
npm run tauri dev
```

运行前端与 Rust 检查：

```bash
cd desktop
npm test
npm run build
npm run backend:test
cd src-tauri
cargo test
```

分别生成纯客户端和内置后端安装包：

```bash
cd desktop
npm run tauri:build:client
npm run tauri:build:standalone
npm run release:rename
```

客户端默认连接自动选择端口的内置服务，也可以填写其他 HTTP 或 HTTPS 后端地址。
访问令牌只保存在进程内存中，不写入浏览器持久化存储。

## Docker 启动

准备 `.env`，设置 `AUTH_SECRET_KEY`、`POSTGRES_PASSWORD` 并同步 `DATABASE_URL` 中的
密码，然后执行：

```bash
docker compose build
docker compose run --rm migrate
docker compose up -d --no-deps app
```

Compose 使用 `postgres-data` 命名卷保存 PostgreSQL 数据。迁移由独立一次性容器执行，
应用容器使用非 root 用户和只读根文件系统运行。验证 HTTP 与 WebSocket：

```bash
curl http://127.0.0.1:8000/health/ready
uv run python -m examples.containerSmokeTest
```

完整说明参见 [Docker 单实例部署](docs/guide/container-deployment.md)。

启动两个应用实例并通过 Redis 路由实时消息：

```bash
docker compose --profile multi-instance up --build -d --wait
uv run python -m examples.containerSmokeTest \
  --base-url http://127.0.0.1:8000 \
  --secondary-base-url http://127.0.0.1:8001
```

项目以 WebSocket 私聊为主线，逐步学习和实践：

- HTTP 与 WebSocket 通信。
- Python 异步编程。
- 在线连接与消息协议管理。
- 面向对象设计与洋葱架构。
- SQLAlchemy 数据持久化。
- 历史消息游标分页、离线主动拉取和发送幂等。
- 用户认证、消息可靠性和自动化测试。
- 一对一会话聚合、成员授权和并发唯一性。
- 累计送达/已读位置与 WebSocket 重连补偿。
- WebSocket 资源限制、结构化日志、存活/就绪检查和优雅关闭。
- Redis Pub/Sub 跨实例实时路由和带 TTL 的在线租约。

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
├── domain/         用户、会话、消息领域对象及不变量
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
- `ConnectionManager` 始终只保存当前进程连接；配置 Redis 后，实例租约和 Pub/Sub
  负责跨实例发现与实时路由，不会把 WebSocket 对象放入 Redis。

## 当前限制

- Compose 使用 PostgreSQL 18；不设置 `DATABASE_URL` 时仍可使用本地 SQLite 后端。
- 已支持短期 Bearer JWT 身份认证和一对一会话成员授权。
- 进程退出后在线状态会丢失，消息保存在配置的 PostgreSQL 或 SQLite 数据库。
- PostgreSQL 运行时使用 asyncpg，Alembic 使用同步 Psycopg；SQLite 保留 aiosqlite。
- 单机和桌面内置模式自动迁移 SQLite；外部部署仍需显式执行 `alembic upgrade head`。
- 离线消息由客户端在 WebSocket 重连后主动提交位置并分批同步。
- 送达和已读位置按用户累计保存，尚不区分同一用户的多个设备。
- `accepted` 只表示服务端已持久化，`pushed` 也不表示用户已经阅读。
- Redis Pub/Sub 只提供至多一次实时路由；丢失事件仍依靠 PostgreSQL 重连补偿。
- 在线状态是带 TTL 的实例租约，暂不支持多设备独立连接和全局立即踢旧连接。

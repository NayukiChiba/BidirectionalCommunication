# 快速开始

## 环境要求

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)（推荐，但不是运行必需）
- Node.js 22 或更高版本（仅用于文档站）

## 最小单机启动

只安装 Python 依赖并直接运行 `main.py`：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe main.py
```

该模式自动生成认证密钥、迁移 `data/chat.sqlite3`，且不连接 PostgreSQL 或 Redis。
使用 uv 时等价命令为：

```bash
uv sync --dev
uv run python main.py
```

默认服务地址：

- HTTP：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`
- WebSocket：`ws://127.0.0.1:8000/ws`（握手需要 Bearer 令牌）

如需修改监听地址，可以设置 `APP_HOST` 和 `APP_PORT` 环境变量。

## 外部数据库与 Redis

PostgreSQL 和 Redis 都是可选扩展。复制 `.env.example`、设置认证密钥和所需连接 URL，
再显式迁移并启动 ASGI 应用：

```powershell
Copy-Item .env.example .env
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

访问健康检查接口，预期响应为：

```json
{
  "status": "alive"
}
```

删除 `DATABASE_URL` 时使用 SQLite，删除 `REDIS_URL` 时使用单进程内存实时路由。
`python main.py` 始终选择这两个本地默认值。

## 运行质量检查

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

领域测试可以单独运行，不需要启动服务器：

```bash
uv run pytest tests/domain
```

## 启动文档站

首次使用时安装 Node.js 依赖：

```bash
cd docs
npm install
```

启动 VitePress 开发服务器：

```bash
npm run dev
```

构建并预览生产版本：

```bash
npm run build
npm run preview
```

## 下一步

先阅读[用户认证与 WebSocket 鉴权](./authentication)，再阅读
[WebSocket 消息协议](./message-protocol)，了解登录、连接、发送和响应流程。

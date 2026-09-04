# 快速开始

## 环境要求

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 或更高版本（仅用于文档站）

## 安装 Python 依赖

在项目根目录执行：

```bash
uv sync --dev
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

将生成的随机值写入 `.env` 的 `AUTH_SECRET_KEY`，然后升级数据库：

```bash
uv run alembic upgrade head
```

## 启动服务

```bash
uv run uvicorn main:app --reload
```

默认服务地址：

- HTTP：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`
- WebSocket：`ws://127.0.0.1:8000/ws`（握手需要 Bearer 令牌）

访问健康检查接口，预期响应为：

```json
{
  "status": "ok"
}
```

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

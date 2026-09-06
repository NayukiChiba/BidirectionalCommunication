# Docker 与 PostgreSQL 部署

Compose 现在运行三个职责独立的容器：PostgreSQL、一次性 Alembic 迁移和聊天应用。
数据库数据保存在 `postgres-data` 命名卷，应用镜像和容器中都不保存数据库文件。

## 文件职责

```text
Dockerfile                      构建非 root 生产应用镜像
.dockerignore                   排除密钥、数据库、本地环境和构建产物
compose.yaml                    编排 PostgreSQL、迁移、应用和持久卷
uv.lock                         固定生产依赖版本和哈希
examples/containerSmokeTest.py  验证映射端口下的 HTTP 与 WebSocket
```

Dockerfile 把依赖声明先于源码复制，使用
`uv sync --frozen --no-dev --no-editable` 恢复锁定依赖。最终镜像不包含 uv 和开发依赖，
以 UID/GID `10001` 的 `appuser:appgroup` 运行。应用保持单进程 Uvicorn，因为当前在线
连接表仍在单个 Python 进程中。

## 准备配置

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

为认证和 PostgreSQL 分别生成随机值并写入 `.env`：

```dotenv
AUTH_SECRET_KEY=<至少32字节随机值>
POSTGRES_USER=chat
POSTGRES_PASSWORD=<URL安全的随机十六进制密码>
POSTGRES_DB=chat
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://chat:<同一密码>@127.0.0.1:5432/chat
APP_PORT=8000
```

Compose 会为容器内应用覆盖主机 URL，使用主机名 `postgres`。`.env` 被 Git 和 Docker
构建上下文排除，密钥与密码不会进入镜像。

## 构建、迁移和启动

```bash
docker compose build
docker compose up -d postgres --wait
docker compose run --rm migrate
docker compose up -d --no-deps app
```

迁移容器等待 PostgreSQL healthy，执行全部 Alembic revision 后退出。迁移没有隐藏在
应用启动函数中；失败时应用不会接管业务流量。

也可以让 Compose 按依赖顺序统一启动：

```bash
docker compose up --build -d --wait
```

查看状态：

```bash
docker compose ps
docker compose logs postgres
docker compose logs migrate
docker compose logs app
```

## 健康与 WebSocket 验收

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
uv run python -m examples.containerSmokeTest \
  --base-url http://127.0.0.1:8000
```

冒烟脚本会完成注册、登录、会话创建和两个带 Bearer 令牌的 WebSocket 消息交换。
`/health/ready` 同时检查数据库连接和 Alembic revision。

## 安全检查

```bash
docker compose exec app id
```

输出应包含 `uid=10001(appuser)`。应用和迁移容器使用只读根文件系统与
`no-new-privileges`，临时文件只写入 `/tmp`。PostgreSQL 端口只绑定宿主机
`127.0.0.1`，不会默认暴露到外部网络。

## 停止与数据卷

```bash
docker compose down
```

该命令保留 `postgres-data`。`docker compose down -v` 会永久删除数据库卷，只能在
明确不需要数据或专门的测试环境中使用。备份、SQLite 数据迁移和回滚演练参见
[PostgreSQL 迁移与事务边界](/guide/postgresql)。

PostgreSQL 已解决 SQLite 文件共享和单写者限制，但当前 WebSocket 在线表没有共享。
因此数据库层可以支持多个客户端进程，整个聊天应用仍不承诺多副本部署；多实例还需
跨实例连接路由。

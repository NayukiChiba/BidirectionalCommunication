# Docker 单实例部署

当前容器方案只承诺一个应用进程、一个 SQLite 持久卷。Docker 镜像是只读的应用模板，
容器是镜像的一次运行实例；删除容器不会删除命名卷中的数据库，但删除卷会永久删除
聊天数据。

## 文件职责

```text
Dockerfile                 构建生产运行镜像
.dockerignore              缩小构建上下文并排除密钥、数据库和本地环境
compose.yaml               编排一次性迁移、应用和 SQLite 命名卷
uv.lock                    固定生产依赖的准确版本和哈希
examples/containerSmokeTest.py  验证容器端口下的 HTTP 与 WebSocket
```

Dockerfile 使用多个层。`pyproject.toml` 和 `uv.lock` 先于源码复制，因此只有依赖声明
变化时才重新执行依赖安装；普通代码修改可以复用依赖缓存。构建阶段使用固定版本 uv
执行 `uv sync --frozen --no-dev --no-editable`，不会复制宿主机平台相关的 `.venv`。

最终运行镜像不包含 uv 和开发依赖，以 UID/GID `10001` 的 `appuser:appgroup` 运行。
应用使用无 `--reload` 的单进程 Uvicorn；WebSocket 帧上限与应用默认 16 KiB 限制一致。

## 准备运行配置

PowerShell：

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

把随机值写入 `.env`：

```dotenv
AUTH_SECRET_KEY=<至少32字节随机值>
APP_PORT=8000
```

`.env` 只在容器运行时由 Compose 读取，已被 Git 和 Docker 构建上下文排除。Dockerfile
和 Compose 都没有默认生产密钥；缺少密钥时 Compose 或应用会立即失败。

## 构建、迁移和启动

在项目根目录执行：

```bash
docker compose build
docker compose run --rm migrate
docker compose up -d --no-deps app
```

迁移是独立、可观察的一次性容器，不隐藏在每个应用进程的启动逻辑中。应用只在迁移
成功后启动。也可以使用下面的便捷命令，让 Compose 根据 `depends_on` 先运行 migrate：

```bash
docker compose up --build -d
```

检查状态和日志：

```bash
docker compose ps
docker compose logs migrate
docker compose logs app
```

## 健康检查

镜像默认 HEALTHCHECK 使用低成本存活接口。Compose 部署覆盖为就绪接口，只有数据库
可以访问且 Alembic revision 与应用一致时，容器才进入 healthy：

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

预期分别返回：

```json
{"status":"alive"}
{"status":"ready"}
```

## WebSocket 端口映射验收

容器 healthy 后，在宿主机执行：

```bash
uv run python -m examples.containerSmokeTest \
  --base-url http://127.0.0.1:8000
```

脚本会通过映射端口完成就绪检查、注册两个临时用户、登录、创建会话、建立两个带
Bearer 令牌的 WebSocket，并验证实时消息和 `accepted` 使用相同服务端消息 ID。测试
通过明确事件和五秒超时结束，不使用固定 sleep。

如果修改 `APP_PORT`，同步修改 `--base-url` 中的端口。

## 安全与镜像检查

确认容器不是 root：

```bash
docker compose exec app id
```

输出应包含 `uid=10001(appuser)`。Compose 还启用只读根文件系统、`no-new-privileges`
和 `/tmp` 临时文件系统；SQLite 只写入挂载的 `/app/data`。

`.dockerignore` 排除：

- `.env`、私钥和本地工具配置；
- `.venv`、缓存和字节码；
- `data/`、SQLite、WAL 和 journal 文件；
- 测试、文档构建产物和 Git 历史。

## 停止与数据保留

```bash
docker compose down
```

该命令删除容器和网络，但保留 `chat-data` 命名卷。`docker compose down -v` 会连同
SQLite 数据永久删除，只能在明确不再需要本地聊天数据时执行。

## 为什么只支持单实例

SQLite 同时只有一个写入者，数据库文件也必须位于单机文件系统。当前在线连接表和
WebSocket 路由保存在单个 Python 进程内；启动多个副本后，一个实例不知道另一个实例
上的在线连接。因此 Compose 不配置副本数，Uvicorn 也不启动多个 worker。多实例需要
先完成 PostgreSQL、共享在线状态和跨实例消息路由设计。

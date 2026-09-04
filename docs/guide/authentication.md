# 用户注册、登录与 WebSocket 鉴权

项目现在通过同一套短期 Bearer JWT 为 HTTP 和 WebSocket 建立可信用户身份。用户名只
用于登录，JWT 的 `sub` 保存稳定 UUID 用户 ID，发送者不再来自 URL 或消息载荷。

## 安装依赖

```bash
uv add pyjwt "pwdlib[argon2]"
```

- `pwdlib[argon2]` 使用专用慢哈希保存密码，自动为每次哈希生成随机盐。
- `PyJWT` 负责 JWT 签名、过期时间和声明验证。
- `python-multipart` 已由 `fastapi[standard]` 提供，用于 OAuth2 登录表单。

不要使用普通 SHA-256、MD5 或自行设计的算法保存密码。它们计算太快，不适合抵抗离线
密码猜测。

## 环境配置

复制 `.env.example` 为不会提交到 Git 的 `.env`，然后生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```dotenv
AUTH_SECRET_KEY=<粘贴生成的随机值>
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=15
```

- 密钥至少 32 字节，没有代码内默认值。
- `.env` 已被 `.gitignore` 忽略。
- Pydantic `SecretStr` 会在配置对象的字符串表示中隐藏密钥。
- JWT 算法固定为 `HS256`，不允许通过环境或令牌载荷改变。
- 访问令牌默认 15 分钟，允许配置 1 到 1440 分钟。

没有 `AUTH_SECRET_KEY` 或密钥过短时，应用拒绝启动。不要记录密钥、访问令牌或明文
密码。

## 用户表

迁移 `f53ad4a832a9` 创建：

```text
users
├── user_id        VARCHAR(36)  PRIMARY KEY
├── username       VARCHAR(32)  UNIQUE NOT NULL
├── password_hash  TEXT         NOT NULL
└── created_at     DATETIME     NOT NULL
```

用户名去除首尾空白并统一为小写，只允许 ASCII 字母、数字、点、下划线和连字符。密码
要求 12 到 128 个字符，不施加必须包含大小写或特殊字符的组合规则。

数据库没有 `password` 字段，只保存 Argon2id 哈希。用户领域实体的 `repr` 也隐藏哈希。

## 注册

```http
POST /auth/register
Content-Type: application/json
```

```json
{
  "username": "alice",
  "password": "correct horse battery staple"
}
```

成功返回：

```json
{
  "user_id": "62fb4b42-109b-4d4a-a8eb-d62107908843",
  "username": "alice"
}
```

用户名规范化后冲突返回 `409`。应用先检查用户名，数据库唯一约束继续保护并发注册
竞态。

## 登录

登录遵循 OAuth2 Password 表单格式：

```http
POST /auth/token
Content-Type: application/x-www-form-urlencoded
```

```text
username=alice&password=correct horse battery staple
```

响应：

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_at": "2026-09-04T03:15:00Z"
}
```

用户名不存在和密码错误使用相同 `401` 响应。用户不存在时仍验证一个固定假哈希，避免
明显的响应时间差异泄露用户名是否存在。

## JWT 语义

载荷只包含：

```json
{
  "sub": "稳定用户 UUID",
  "iat": "签发时间",
  "exp": "过期时间"
}
```

JWT 是 Base64URL 编码并签名，不是加密。任何拿到令牌的人都可以读取载荷，因此不能
放入密码、密码哈希、密钥或敏感隐私。

解码时显式使用：

```python
jwt.decode(token, secretKey, algorithms=["HS256"])
```

服务端同时要求 `sub`、`iat` 和 `exp`，验证签名、算法白名单、过期时间和 UUID 类型，
最后查询数据库确认用户仍然存在。

## HTTP Bearer

```http
GET /auth/me
Authorization: Bearer <JWT>
```

历史接口不再接受 `user_id`：

```http
GET /messages/history?peer_id=<对方用户ID>&limit=50
Authorization: Bearer <JWT>
```

当前用户始终从 Bearer 令牌取得，查询参数只能指定对方用户。

## WebSocket 握手

WebSocket URL 不再携带身份：

```text
ws://127.0.0.1:8000/ws
```

握手必须包含：

```http
Authorization: Bearer <JWT>
```

Python `websockets` 示例：

```python
async with websockets.connect(
    "ws://127.0.0.1:8000/ws",
    additional_headers={"Authorization": f"Bearer {accessToken}"},
) as websocket:
    ...
```

服务端在 `accept()` 和登记在线连接之前验证令牌。无令牌、非法令牌和过期令牌使用
WebSocket 关闭码 `4401` 拒绝。即使 URL 仍附加伪造的 `?user_id=...`，该参数也不会
参与身份建立。

选择 Authorization 头是为了避免令牌进入 URL、浏览器历史和常见访问日志。原生浏览器
WebSocket API 不能设置自定义 Authorization 头；加入浏览器客户端时需要设计安全的
HttpOnly Cookie 或受约束子协议方案，不能退回 URL Token。

## 认证与授权的区别

- 认证回答：当前请求是谁？
- 授权回答：这个用户是否有权访问目标资源？

本 Issue 只建立可信身份。用户登录成功不代表可以读取或向任意会话发送消息；会话成员
关系和权限检查属于 Issue 18。

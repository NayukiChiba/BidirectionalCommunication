# WebSocket 消息协议

## 建立连接

客户端通过查询参数提供临时用户标识：

```text
ws://127.0.0.1:8000/ws?user_id=user-a
```

当前版本没有身份认证，`user_id` 由客户端自行指定，仅适合本地学习和测试。

## 发送消息

客户端发送 `send_message` 命令：

```json
{
  "type": "send_message",
  "recipient_id": "user-b",
  "content": "Hello World",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `type` | 固定为 `send_message` |
| `recipient_id` | 接收方用户标识，最长 64 个字符 |
| `content` | 非空文字消息，最长 2000 个字符 |
| `client_message_id` | 客户端提供的 UUID，用于关联消息和 ACK |

发送者身份由当前 WebSocket 连接决定。客户端不能在消息载荷中传入 `sender_id`。

## 接收消息事件

在线接收方会收到：

```json
{
  "type": "message",
  "server_message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
  "sender_id": "user-a",
  "recipient_id": "user-b",
  "content": "Hello World",
  "sent_at": "2026-08-07T08:00:00Z"
}
```

`server_message_id` 由服务端生成。`sent_at` 在当前版本映射消息领域创建时间，并使用
带时区的 UTC 时间。

## ACK 确认

消息成功投递到目标连接后，发送方收到：

```json
{
  "type": "ack",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
  "server_message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60"
}
```

当前 ACK 只表示服务端已向目标 WebSocket 连接执行发送，不表示用户已经阅读消息。

## 错误事件

协议或投递失败时，发送方收到：

```json
{
  "type": "error",
  "code": "recipient_offline",
  "message": "用户 user-b 不在线",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"
}
```

当前错误码：

| 错误码 | 含义 |
| --- | --- |
| `invalid_json` | 消息不是合法 JSON |
| `invalid_message` | 命令字段或领域值不合法 |
| `recipient_offline` | 目标用户当前没有可用连接 |

## 自发消息

允许发送方将 `recipient_id` 设置为自己的用户标识。当前连接会依次收到 `message`
事件和 `ack`。

## 重复登录

同一 `user_id` 建立第二个 WebSocket 连接时：

- 新连接成为当前有效连接。
- 旧连接以关闭码 `4001` 关闭。
- 固定关闭原因为“该账号已在其他连接登录”。
- 旧连接退出不会清除新连接。

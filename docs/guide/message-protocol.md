# WebSocket 消息协议

## 建立连接

客户端连接固定 WebSocket 地址：

```text
ws://127.0.0.1:8000/ws
```

握手必须使用 `Authorization: Bearer <JWT>`。服务端在接受连接前验证令牌，并从 JWT
的 `sub` 和数据库用户记录确定发送者。URL 查询参数和消息载荷都不能指定发送者。

## 发送消息

客户端发送 `send_message` 命令：

```json
{
  "type": "send_message",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "content": "Hello World",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `type` | 固定为 `send_message` |
| `conversation_id` | 已创建的一对一会话 UUID |
| `content` | 非空文字消息，最长 2000 个字符 |
| `client_message_id` | 客户端提供的 UUID，同时作为发送重试的幂等键 |

发送者身份由当前 WebSocket 连接的已验证令牌决定。客户端不能在消息载荷中传入
`sender_id`。
服务端加载会话并检查发送者是成员，接收者由会话中的另一名成员确定。

## 接收消息事件

在线接收方会收到：

```json
{
  "type": "message",
  "server_message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
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
使用相同 `client_message_id` 重试时，服务端返回原消息的同一个 `server_message_id`。
实时消息事件可能再次推送，客户端应按 `server_message_id` 去重。

历史查询和离线恢复参见[历史分页、离线恢复与幂等](/guide/message-history)。

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
| `delivery_failed` | 目标连接存在，但实时推送过程失败 |
| `message_storage_failed` | 消息保存失败，因此没有执行实时推送 |
| `conversation_unavailable` | 会话不存在或当前用户不是成员 |

一对一会话固定包含两名不同用户，因此不支持自发消息。

## 重复登录

同一已认证用户建立第二个 WebSocket 连接时：

- 新连接成为当前有效连接。
- 旧连接以关闭码 `4001` 关闭。
- 固定关闭原因为“该账号已在其他连接登录”。
- 旧连接退出不会清除新连接。

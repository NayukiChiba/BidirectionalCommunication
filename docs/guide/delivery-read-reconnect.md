# 送达、已读与重连补偿

消息可靠性不能只用一个“成功”表示。当前协议明确区分四个阶段：

| 状态 | 谁确认 | 准确含义 |
| --- | --- | --- |
| `accepted` | 服务端数据库 | 消息已经校验、持久化并提交 |
| `pushed` | 服务端 WebSocket 层 | 服务端已经尝试并完成一次连接写入，仅供观测 |
| `delivered` | 接收客户端 | 客户端明确确认已经持久处理至某个消息位置 |
| `read` | 接收客户端 | 用户界面明确确认已经阅读至某个消息位置 |

`pushed` 不等于 `delivered`：服务端完成 WebSocket 写入后，客户端可能在读取或保存前
断线。`delivered` 也不等于 `read`：消息进入客户端本地存储，不代表用户打开了会话。

## 发送方持久化确认

发送成功后，发送方收到：

```json
{
  "type": "accepted",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
  "server_message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60",
  "push_status": "recipient_offline"
}
```

`accepted` 是发送用例的成功结果。`push_status` 只记录本次实时推送观测：

- `pushed`：已经写入接收者当前 WebSocket。
- `recipient_offline`：接收者没有当前连接。
- `failed`：存在连接，但写入失败。

后三种结果都不回滚已经提交的消息。发送方应保存 `server_message_id`，不能把
`push_status=pushed` 显示成“对方已读”。

## 累计确认

客户端在可靠保存消息后提交累计送达位置：

```json
{
  "type": "acknowledge_position",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "position_type": "delivered",
  "message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60"
}
```

用户实际阅读到该位置后，把 `position_type` 改为 `read`。服务端返回当前有效位置：

```json
{
  "type": "position_ack",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "position_type": "delivered",
  "message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60",
  "advanced": true
}
```

位置按 `(created_at, message_id)` 排序。数据库为每名会话成员保存：

```text
delivered_created_at + delivered_message_id
read_created_at      + read_message_id
```

条件 `UPDATE` 只接受严格靠后的目标，因此重复确认和较旧确认返回
`advanced=false`，并发提交也不能使位置倒退。已读位置不能超过已送达位置；目标消息
必须属于该会话，确认者也必须是会话成员。

累计位置表示“此前有序消息都已经处理”，比每条消息一个可变布尔值写入更少、查询更
直接。但它依赖稳定的全序；如果以后支持删除、分支消息或多设备独立进度，需要重新
定义位置语义。

## 重连同步

首次同步或本地没有位置时：

```json
{
  "type": "sync_messages",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "after_message_id": null,
  "limit": 100
}
```

客户端已经可靠保存到某条消息时，将其 ID 作为 `after_message_id`。该字段同时是一次
累计 `delivered` 确认，服务端随后返回该位置之后的消息：

```json
{
  "type": "sync_result",
  "conversation_id": "31487468-dd7c-4de9-ac2b-fd5b979da2b8",
  "messages": [],
  "has_more": false
}
```

同步请求可以重复。相同位置会得到相同范围的消息，不创建新领域消息，也不倒退累计
位置。网络层仍可能重复返回同一事件，客户端必须用 `server_message_id` 幂等写入本地
存储，才能获得用户可感知的“效果上恰好一次”。

## 客户端集成顺序

1. 收到实时 `message` 或 `sync_result.messages` 后，先按 `server_message_id` 幂等写入
   本地存储。
2. 本地事务成功后，提交最后连续保存消息的 `delivered` 位置。
3. 用户界面实际展示并阅读后，提交最后连续阅读消息的 `read` 位置。
4. WebSocket 重连后，从本地持久化的最后连续消息 ID 发起 `sync_messages`。
5. 按顺序处理返回消息；若 `has_more=true`，使用本批最后一条消息继续同步。
6. 响应丢失时原样重试，不生成新的客户端消息 ID，也不清空本地去重记录。

当前只保存每个用户在会话中的一份累计位置，不区分手机、桌面等多个设备。

## 可靠性边界

- 至多一次会漏消息，不适合聊天历史。
- 当前实时推送和重连同步采用至少一次语义，允许重复但不允许消息只存在于网络。
- 分布式系统无法仅靠一次 WebSocket `send` 承诺网络层恰好一次。
- 服务端消息幂等键、稳定消息 ID、累计位置和客户端去重共同提供效果上的恰好一次。

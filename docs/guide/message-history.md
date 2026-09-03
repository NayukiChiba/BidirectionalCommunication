# 历史分页、离线恢复与幂等

数据库现在是可靠消息来源，WebSocket 只负责低延迟实时通知。接收者离线或实时推送
失败时，已提交消息仍然保留，客户端可以通过 HTTP 历史接口主动补齐。

## 历史消息接口

```http
GET /messages/history?user_id=user-a&peer_id=user-b&limit=50
```

响应按 `(created_at, server_message_id)` 从旧到新排列：

```json
{
  "messages": [
    {
      "server_message_id": "e6935df2-343f-4915-bcb7-fbd45891fd60",
      "client_message_id": "5cbe59a7-1c45-4dd9-9302-d9eb2586bb6b",
      "sender_id": "user-a",
      "recipient_id": "user-b",
      "content": "Hello World",
      "created_at": "2026-09-03T08:00:00Z"
    }
  ],
  "next_cursor": "eyJ2ZXJzaW9uIjoxLC4uLn0",
  "has_more": false
}
```

- `limit` 默认 50，范围是 1 到 100。
- `next_cursor` 指向本页最后一条消息；空页返回 `null`。
- `has_more` 表示当前游标之后是否已经存在下一页。
- 游标是不透明文本，客户端应原样保存和传回，不应解析或修改。

继续查询：

```http
GET /messages/history?user_id=user-a&peer_id=user-b&limit=50&cursor=<next_cursor>
```

游标是排他的，因此返回结果不包含游标所指消息。

## 为什么不用 offset

偏移分页类似：

```sql
LIMIT 50 OFFSET 10000
```

数据库通常需要跳过前面大量记录。如果分页过程中插入了新消息，行的位置还可能移动，
导致重复或跳项。

当前游标保存 `(created_at, message_id)`，下一页使用“大于游标”的条件。查询成本不随
前面已有多少页线性增长，而且新数据不会改变已读取消息的相对位置。

`created_at` 不是唯一值，两条消息可能具有完全相同的时间。因此必须加入唯一
`message_id` 作为决胜字段；查询和排序始终同时使用这两个字段。

## 查询索引

第二个 Alembic revision 将旧索引替换为：

```text
(sender_id, recipient_id, created_at, message_id)
```

单聊查询包含两个方向：

```sql
(sender_id = :user AND recipient_id = :peer)
OR
(sender_id = :peer AND recipient_id = :user)
```

两个分支都对 `sender_id` 和 `recipient_id` 使用等值条件，因此 SQLite 可以为两个
分支复用同一个复合索引。集成测试通过 `EXPLAIN QUERY PLAN` 验证使用该索引，而不是
维护一个没有收益的反向重复索引。

## 离线消息恢复

本阶段不创建额外离线队列。流程是：

```text
消息事务提交
    ↓
尝试 WebSocket 推送
    ├── 在线：立即收到
    └── 离线或失败：消息仍在 SQLite
                         ↓
                 客户端重新连接
                         ↓
              携带上次游标主动查询
```

客户端应在本地保存最后同步成功的 `next_cursor`。重新连接后，用该游标调用历史接口，
直到 `has_more` 为 `false`。当前没有已读和送达位置；这些属于 Issue 19。

## 幂等发送

幂等键是：

```text
(sender_id, client_message_id)
```

客户端第一次发送时，服务端生成 `server_message_id` 并保存消息。如果 ACK 丢失，客户
端使用相同 `client_message_id` 重试，服务端查询并返回原消息，因此不会创建第二行，
ACK 中的 `server_message_id` 也保持相同。

数据库唯一约束仍然必需。两个并发请求可能同时执行“查询不到”，随后一起插入；只有
数据库能在最终写入点原子地接受一个并拒绝另一个。应用捕获唯一约束冲突后，会创建
新的 UoW 查询胜出的原消息。

重复请求可能再次触发同一条消息的 WebSocket 推送，但使用的是相同
`server_message_id`。实时事件仍然不承诺恰好一次，客户端可以根据服务端消息 ID 去重。

同一个发送者不能把一个 `client_message_id` 用于两条不同业务消息；重复使用时，原消息
始终胜出。

## 当前身份边界

项目尚未实现认证，因此 HTTP 接口中的 `user_id` 仍由调用者提供，只适合当前学习阶段。
Issue 17 接入可信身份后，查询用户应来自访问令牌，不能继续信任任意查询参数。

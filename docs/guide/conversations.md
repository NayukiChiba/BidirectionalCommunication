# 一对一会话聚合与成员权限

`Conversation` 是一对一聊天的稳定业务身份，也是成员规则的一致性边界。认证只回答
“当前用户是谁”，会话成员关系继续回答“这个用户能否访问这段聊天”。

## 统一业务语言

- `Conversation`：恰好连接两名不同用户的一对一会话聚合根。
- 会话成员：通过 `UserId` 引用用户，不把密码、在线连接等用户状态放入会话。
- `ChatMessage`：属于一个 `conversationId`，由一个会话成员发送给另一名成员。
- 历史消息：按 `conversationId` 和稳定游标分页，不再拼接两个方向的用户条件。

`Conversation` 负责成员数量、成员身份判断和取得另一名成员。消息可以独立分页持久化，
不会作为无限增长的列表装入聚合根。在线 WebSocket 是短暂基础设施状态，也不属于该
聚合；用户离线、重连或多设备登录都不改变会话成员。

## 数据库结构和不变量

```text
conversations
├── conversation_id    PRIMARY KEY
├── member_pair_key    UNIQUE NOT NULL
└── created_at          NOT NULL

conversation_members
├── conversation_id    FOREIGN KEY → conversations
├── user_id             FOREIGN KEY → users
├── member_position     CHECK IN (1, 2)
├── PRIMARY KEY (conversation_id, user_id)
└── UNIQUE (conversation_id, member_position)

messages
└── conversation_id    FOREIGN KEY → conversations
```

领域模型要求成员集合恰好包含两名不同用户。数据库主键防止同一成员重复，槽位约束
限制一个会话最多两个位置；Repository 在同一事务中保存根记录和两个成员记录。

`member_pair_key` 对两个用户 ID 排序后生成，因此 Alice/Bob 和 Bob/Alice 得到同一个
值。唯一约束是并发安全的最终防线：两个请求即使同时查询到不存在，也只有一个能够
插入，另一个捕获冲突后读取胜出的会话。

消息索引为：

```text
(conversation_id, created_at, message_id)
```

它直接服务“查询一个会话中某游标之后的消息”这一查询。`message_id` 是相同创建时间
下的唯一决胜字段，因此分页不会重复或跳项。

## HTTP 与 WebSocket 流程

创建或获取会话：

```http
POST /conversations
Authorization: Bearer <JWT>
Content-Type: application/json

{"peer_id":"<另一名用户 UUID>"}
```

发送消息使用服务端返回的会话 ID：

```json
{
  "type": "send_message",
  "conversation_id": "<会话 UUID>",
  "content": "Hello",
  "client_message_id": "<客户端消息 UUID>"
}
```

查询历史：

```http
GET /conversations/<会话 UUID>/messages?limit=50&cursor=<可选游标>
Authorization: Bearer <JWT>
```

发送和查询都会先加载 `Conversation` 并验证当前用户是成员。会话不存在和用户不是成员
对外都返回 `conversation_unavailable`，避免攻击者通过错误差异探测会话 ID。

## 三个关键结论

1. 用户登录只证明身份，没有自动获得任意会话的数据权限。
2. 成员组合唯一、成员不重复和成员槽位不能只靠应用层先查询，数据库约束必须参与
   保护并发写入。
3. 在线连接生命周期短、变化频繁且属于 WebSocket 基础设施；把它放入持久化聚合会把
   领域规则与网络连接错误地耦合。

# 消息领域模型

## 当前范围

当前领域层表达用户标识、`Conversation` 聚合和聊天消息。它不负责 WebSocket 连接、
协议解析、消息投递或数据持久化；会话聚合详见
[一对一会话聚合与成员权限](/guide/conversations)。

领域代码位于 `src/domain/`，只依赖 Python 标准库。

## 领域概念

| 名称 | 类型 | 含义 |
| --- | --- | --- |
| `UserId` | 值对象 | 发送者或接收者的用户标识 |
| `MessageId` | 值对象 | 服务端生成的消息唯一标识 |
| `ClientMessageId` | 值对象 | 客户端生成的消息关联标识 |
| `ConversationId` | 值对象 | 消息所属会话的稳定标识 |
| `MessageContent` | 值对象 | 经过规范化的文字消息内容 |
| `ChatMessage` | 实体 | 由 `MessageId` 标识的一条聊天消息 |

`MessageId` 和 `ClientMessageId` 即使包装同一个 UUID，也表示不同概念，不能互换。

## 业务不变量

### `UserId`

- 必须是字符串。
- 去除首尾空白后不能为空。
- 创建后不可修改。

### `MessageId`

- 必须包装 UUID。
- 由服务端使用 UUID4 生成。
- 创建后不可修改。

### `ClientMessageId`

- 必须包装 UUID。
- 由客户端提供，用于关联消息和 `accepted` 持久化确认。
- 创建后不可修改。

### `MessageContent`

- 必须是字符串。
- 去除首尾空白后不能为空。
- 规范化后的长度不能超过 2000 个字符。
- 创建后不可修改。

### `ChatMessage`

- 必须由上述领域值对象组合，不能直接使用原始字符串或 UUID 代替。
- 以 `MessageId` 判断两条消息是否为同一实体。
- `created_at` 必须包含时区，并统一转换为 UTC。
- 必须包含 `ConversationId`；发送服务从已验证会话中取得另一名成员作为接收者。
- 创建后不可修改。

## 创建入口

`create_chat_message` 是当前消息实体的创建函数。调用方提供会话、客户端消息标识、
发送者、接收者和消息内容；函数补充服务端 `MessageId` 与 UTC 创建时间。

这个创建过程目前没有额外状态或独立生命周期，因此使用函数比增加工厂类更清晰。

## 领域异常

违反领域规则时抛出 `DomainError` 的具体子类：

| 异常 | 表达的规则错误 |
| --- | --- |
| `InvalidUserId` | 用户标识不合法 |
| `InvalidMessageId` | 服务端消息标识不合法 |
| `InvalidClientMessageId` | 客户端消息标识不合法 |
| `InvalidMessageContent` | 消息内容不合法 |
| `InvalidMessageCreatedAt` | 消息创建时间不合法 |
| `InvalidChatMessage` | 消息没有由正确的领域概念组成 |

这些异常只描述业务规则，不包含 HTTP 状态码、WebSocket 关闭码或协议错误码。

## 传输模型与领域模型

传输模型属于 WebSocket 协议边界，应用命令表达系统用例输入，领域模型属于业务规则
边界。当前转换显式完成：

| 方向 | 负责位置 | 说明 |
| --- | --- | --- |
| `SendMessagePayload` → `SendMessageCommand` | WebSocket 路由 | 解析协议字段，并补充来自当前连接的可信发送者身份 |
| `SendMessageCommand` → `ChatMessage` | `SendMessageService` | 加载会话、验证成员，再通过 `create_chat_message` 创建消息 |
| `ChatMessage` → WebSocket 消息事件 | `WebSocketMessageNotifier` | 将领域字段转换成客户端协议字段并尝试实时投递 |

Pydantic 负责检查外部数据结构，领域对象继续保护业务不变量。因此，即使传输模型已经
校验通过，也必须经过值对象和实体的公开创建入口。

## 命名约定

- 领域类型使用业务名称：`ChatMessage`、`MessageContent`。
- 标识类型明确来源：服务端使用 `MessageId`，客户端使用 `ClientMessageId`。
- WebSocket 输入模型使用 `Payload` 后缀，应用用例输入使用 `Command` 后缀。
- 时间在领域内称为 `created_at`，对外协议字段仍保持 `sent_at`。
- 领域异常使用 `Invalid...` 命名，只表达被违反的领域规则。

当前的 `SendMessageCommand` 是应用命令。发送给 WebSocket 客户端的 `message` 数据是
传输事件，不是领域事件。

---
layout: home

hero:
  name: BidirectionalCommunication
  text: 从 WebSocket 私聊开始学习分层架构
  tagline: 使用 FastAPI、纯 Python 领域模型和自动化测试逐步构建可靠的双向通信后端
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/getting-started
    - theme: alt
      text: 阅读领域模型
      link: /domain/message-model

features:
  - title: WebSocket 双向通信
    details: 支持在线用户实时发送消息、ACK、协议错误和重复登录连接替换。
  - title: 纯 Python 领域模型
    details: 使用值对象和实体维护消息标识、内容与 UTC 创建时间等业务不变量。
  - title: 渐进式架构学习
    details: 先验证真实需求，再逐步引入 Domain、Application、同步 SQLAlchemy 和 Unit of Work。
  - title: 自动化行为保护
    details: 使用领域单元测试和 WebSocket 验收测试共同保护内部规则与外部协议。
---

## 当前阶段

项目已经完成单进程 WebSocket 私聊的 v0.1 和 `M3 分层内核 v0.2`，正在学习
`M4 持久化聊天 v0.3`。当前已建立同步 SQLAlchemy 映射和事务实验，但应用仍使用
内存 Repository；数据库接入应用用例将在后续 Issue 中完成。

## 文档导航

- [快速开始](/guide/getting-started)：安装依赖、启动服务并运行测试。
- [WebSocket 消息协议](/guide/message-protocol)：连接方式、消息结构和错误响应。
- [架构与组合根](/guide/architecture)：各层职责、依赖方向和应用组装。
- [关系建模与 SQLAlchemy](/guide/database-foundations)：消息表、索引、ORM 映射和同步事务。
- [消息领域模型](/domain/message-model)：领域概念、不变量和传输转换边界。

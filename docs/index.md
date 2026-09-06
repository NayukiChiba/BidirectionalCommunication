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
    details: 支持实时发送、幂等重试、历史分页、离线恢复和重复登录连接替换。
  - title: 纯 Python 领域模型
    details: 使用值对象和实体维护消息标识、内容与 UTC 创建时间等业务不变量。
  - title: 渐进式架构学习
    details: 先验证真实需求，再逐步引入 Domain、Application、异步 SQLAlchemy 和 Unit of Work。
  - title: 自动化行为保护
    details: 使用领域单元测试和 WebSocket 验收测试共同保护内部规则与外部协议。
---

## 当前阶段

项目已经完成单进程 WebSocket 私聊 v0.1、`M3 分层内核 v0.2`、
`M4 持久化聊天 v0.3` 和 `M5 可信私聊 v0.4`。当前通过 Repository 与 Unit of Work
使用异步 SQLAlchemy，
由 Alembic 管理数据库结构，并提供稳定游标历史查询、离线主动恢复和消息幂等。
每个并发 Task 使用独立 AsyncSession，数据库等待不会阻塞其他连接的事件循环调度。
HTTP 与 WebSocket 已使用同一短期 Bearer JWT 建立可信用户身份。
一对一会话现在具有稳定身份和数据库成员约束，只有会话成员可以发送或读取消息。
累计送达与已读位置只会向前推进，客户端可在 WebSocket 重连后幂等补齐缺失消息。

## 文档导航

- [快速开始](/guide/getting-started)：安装依赖、启动服务并运行测试。
- [WebSocket 消息协议](/guide/message-protocol)：连接方式、消息结构和错误响应。
- [历史分页、离线恢复与幂等](/guide/message-history)：游标、主动拉取和重试语义。
- [架构与组合根](/guide/architecture)：各层职责、依赖方向和应用组装。
- [关系建模与 SQLAlchemy](/guide/database-foundations)：消息表、索引、ORM 映射和事务基础。
- [异步 SQLAlchemy](/guide/async-sqlalchemy)：AsyncEngine、Task 级 Session 和显式 I/O。
- [用户认证与 WebSocket 鉴权](/guide/authentication)：Argon2id、JWT、Bearer 和环境密钥。
- [一对一会话聚合与成员权限](/guide/conversations)：会话身份、成员约束和授权边界。
- [送达、已读与重连补偿](/guide/delivery-read-reconnect)：累计位置、确认语义和客户端同步循环。
- [质量、可观测性与安全基线](/guide/quality-security)：测试层级、资源限制、日志和健康检查。
- [Docker 单实例部署](/guide/container-deployment)：镜像构建、显式迁移、持久卷和冒烟测试。
- [Alembic 数据库迁移](/guide/database-migrations)：版本历史、升级降级和开发部署流程。
- [Repository 与 Unit of Work](/guide/repository-unit-of-work)：持久化端口、事务边界和失败恢复。
- [消息领域模型](/domain/message-model)：领域概念、不变量和传输转换边界。

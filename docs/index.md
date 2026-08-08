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
    details: 先验证真实需求，再逐步引入 Domain、Application、Repository 和 Unit of Work。
  - title: 自动化行为保护
    details: 使用领域单元测试和 WebSocket 验收测试共同保护内部规则与外部协议。
---

## 当前阶段

项目已经完成单进程 WebSocket 私聊的 v0.1，并进入 `M3 分层内核 v0.2`。当前已经
提取消息领域模型和发送消息应用用例，通过最小存储端口与实时通知端口隔离内存存储和
WebSocket 技术细节，尚未引入数据库、事务和通用架构框架。

## 文档导航

- [快速开始](/guide/getting-started)：安装依赖、启动服务并运行测试。
- [WebSocket 消息协议](/guide/message-protocol)：连接方式、消息结构和错误响应。
- [消息领域模型](/domain/message-model)：领域概念、不变量和传输转换边界。

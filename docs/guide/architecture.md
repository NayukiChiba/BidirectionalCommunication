# 架构与组合根

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `domain` | 表达消息领域概念、不变量和领域异常 |
| `application` | 表达发送消息用例、命令、结果及所需端口 |
| `adapters` | 使用内存和 WebSocket 实现应用端口及连接管理 |
| `entrypoints` | 处理 FastAPI 路由、Pydantic 协议模型和错误映射 |
| `bootstrap.py` | 创建具体对象、注入依赖并管理应用生命周期 |
| `main.py` | 作为唯一启动入口暴露 FastAPI `app` |

## 依赖方向

```text
main
  ↓
bootstrap
  ├── entrypoints
  ├── adapters
  └── application
         ↓
       domain

entrypoints → application
adapters → application + domain
application → domain
domain → Python 标准库
```

内层不能导入外层。尤其禁止 Application 导入具体 Adapter，也禁止 Domain 导入
Application、FastAPI、Pydantic 或数据库框架。

## 程序入口与请求入口

`main.py` 是进程的唯一启动入口：

```python
from bootstrap import create_app

app = create_app()
```

`entrypoints/` 表示外部请求进入应用核心的输入适配器，并不是另一个可执行程序入口。
它负责将 WebSocket JSON 转换为 `SendMessageCommand`，再将应用结果转换为 ACK 或
错误事件。

## 组合根

`bootstrap.create_app()` 是唯一组合根，负责创建：

```text
ConnectionManager
InMemoryMessageRepository
WebSocketMessageNotifier
SendMessageService
FastAPI
```

具体依赖在组合根中通过构造参数注入。组合后的对象保存在 `app.state`，用于应用生命
周期管理和外部行为测试。业务代码不会通过全局注册表查找依赖。

## WebSocket 的两个方向

Entrypoint 处理输入和当前调用者响应：

```text
发送者 WebSocket
→ SendMessagePayload
→ SendMessageCommand
→ SendMessageService
→ ACK / ErrorEvent
```

Adapter 实现应用主动要求的接收者通知：

```text
ChatMessage
→ WebSocketMessageNotifier
→ ConnectionManager
→ 接收者 WebSocket
```

两者都使用 WebSocket，但分别属于输入适配和输出适配。

## 自动化边界保护

架构测试会检查：

- Domain 和 Application 没有反向依赖外层。
- Adapters 不依赖 Entrypoints、Bootstrap 或 Main。
- Entrypoints 不创建或导入具体 Adapter。
- 具体 Repository、Notifier、Service 和连接管理器只在 Bootstrap 中创建。
- Main 只导入组合根。

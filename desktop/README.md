# 桌面客户端

该目录包含 BidirectionalCommunication 的 Tauri 2 桌面客户端：

- Vue 3 + TypeScript 负责界面和视图状态。
- Rust/Tauri 命令负责 HTTP API 请求。
- Rust WebSocket 客户端负责 Bearer 握手、长连接和事件转发。
- 收到消息后按服务端消息 ID 去重，并推进累计送达/已读位置。
- 连接异常时使用 1 秒到 15 秒的指数退避自动重连。

## 开发

先在仓库根目录启动 FastAPI 后端，再执行：

```bash
npm install
npm run tauri dev
```

登录页默认使用 `http://127.0.0.1:8000`，可改为其他 HTTP 或 HTTPS 地址。

## 验证与打包

```bash
npm test
npm run build
cd src-tauri
cargo test
cd ..
npm run tauri build
```

Windows NSIS 安装包生成在：

```text
src-tauri/target/release/bundle/nsis/
```

## 发布

推送 `v*` 格式的 Tag 后，GitHub Actions 会在 Windows Runner 上运行前端测试、构建
NSIS 安装程序，并在构建成功后创建 GitHub Release 和上传 EXE：

```bash
git tag v0.1.1
git push origin v0.1.1
```

Tag 版本必须与 `package.json`、`src-tauri/Cargo.toml` 和
`src-tauri/tauri.conf.json` 中的版本一致。如果存在 `changelogs/<tag>.md`，Release
使用该文件作为说明；否则由 GitHub 自动生成发布说明。

## 安全边界

- 密码仅用于当前登录或注册请求。
- 访问令牌只保存在运行时内存中，不写入 `localStorage`。
- 本地仅保存服务器地址和最近会话的非敏感索引。
- WebSocket 鉴权由 Rust 层设置 `Authorization: Bearer` 请求头。

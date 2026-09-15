# 桌面客户端

该目录包含 BidirectionalCommunication 的 Tauri 2 桌面客户端：

- Vue 3 + TypeScript 负责界面和视图状态。
- Rust/Tauri 命令负责 HTTP API 请求。
- PyInstaller sidecar 内置 FastAPI、SQLite 和 Alembic 迁移。
- Rust WebSocket 客户端负责 Bearer 握手、长连接和事件转发。
- 收到消息后按服务端消息 ID 去重，并推进累计送达/已读位置。
- 连接异常时使用 1 秒到 15 秒的指数退避自动重连。

## 发布版本

- 完整版 `BidirectionalCommunication_0.5_x64-setup.exe`：自带 FastAPI 和 SQLite，
  开箱即用。
- 纯客户端版 `BidirectionalCommunicationClient_0.5_x64-setup.exe`：不包含后端，
  连接本机 8000 端口或用户填写的远程服务。

安装包文件名使用 ASCII，因为 GitHub 会剥离 Release 资产名中的非字母数字字符，
中文名会导致两个安装包重名冲突。

Cargo、npm 和 Tauri 内部遵循 SemVer，使用 `0.5.0`；对外 Tag、Release 和安装包名称
使用 `0.5`。

## 直接使用完整版

安装并运行桌面客户端后，会自动：

1. 在随机回环端口启动内置后端。
2. 在应用数据目录生成随机认证密钥。
3. 创建或升级 `backend/chat.sqlite3`。
4. 在主程序退出时终止 sidecar。

Windows 数据默认位于：

```text
%APPDATA%\com.nayukichiba.bidirectionalcommunication\backend
```

不需要单独安装 Python、Docker、PostgreSQL 或 Redis。登录页仍允许填写远程后端地址，
用于让多台电脑连接同一个服务。

## 开发

在仓库根目录和 `desktop` 目录分别安装依赖：

```bash
uv sync --dev
cd desktop
npm install
npm run tauri dev
```

默认 `npm run tauri dev` 启动纯客户端开发模式；完整版开发模式会先调用 PyInstaller
构建 sidecar：

```bash
npm run tauri:dev:standalone
```

## 验证与打包

```bash
npm test
npm run build
npm run backend:build
npm run backend:test
cd src-tauri
cargo test
cd ..
npm run tauri:build:client
npm run tauri:build:standalone
npm run release:rename
```

Windows NSIS 安装包生成在：

```text
src-tauri/target/release/bundle/nsis/
```

## 发布

推送 `v*` 格式的 Tag 后，GitHub Actions 会在 Windows Runner 上运行前端测试，构建
纯客户端和完整版两个 NSIS 安装程序，并在构建成功后创建 GitHub Release 和上传：

```bash
git tag v0.5
git push origin v0.5
```

Tag 版本必须与 `package.json`、`src-tauri/Cargo.toml` 和
`src-tauri/tauri.conf.json` 中的版本一致。如果存在 `changelogs/<tag>.md`，Release
使用该文件作为说明；否则由 GitHub 自动生成发布说明。

## 安全边界

- 密码仅用于当前登录或注册请求。
- 访问令牌只保存在运行时内存中，不写入 `localStorage`。
- 本地仅保存服务器地址和最近会话的非敏感索引。
- WebSocket 鉴权由 Rust 层设置 `Authorization: Bearer` 请求头。

use std::ffi::OsString;
use std::net::TcpListener;
use std::sync::Mutex as StandardMutex;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use http::header::{HeaderValue, AUTHORIZATION};
use reqwest::{Client, Response, StatusCode};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};
use url::Url;

const REQUEST_TIMEOUT_SECONDS: u64 = 15;
const EMBEDDED_BACKEND_START_ATTEMPTS: usize = 600;
const EMBEDDED_BACKEND_RETRY_MILLISECONDS: u64 = 100;
const STANDALONE_APP_IDENTIFIER: &str = "com.nayukichiba.bidirectionalcommunication";
const EXTERNAL_SERVER_URL: &str = "http://127.0.0.1:8000";

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CommandError {
    code: String,
    message: String,
    status: Option<u16>,
}

impl CommandError {
    fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            status: None,
        }
    }

    fn with_status(
        code: impl Into<String>,
        message: impl Into<String>,
        status: StatusCode,
    ) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            status: Some(status.as_u16()),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct UserIdentity {
    user_id: String,
    username: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct AccessToken {
    access_token: String,
    token_type: String,
    expires_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct Conversation {
    conversation_id: String,
    member_ids: Vec<String>,
    members: Vec<ConversationMember>,
    created_at: String,
    created: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct ConversationMember {
    user_id: String,
    username: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct HistoryMessage {
    server_message_id: String,
    client_message_id: String,
    conversation_id: String,
    sender_id: String,
    recipient_id: String,
    content: String,
    created_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct HistoryPage {
    messages: Vec<HistoryMessage>,
    next_cursor: Option<String>,
    has_more: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct WebSocketStatus {
    state: &'static str,
    code: Option<u16>,
    reason: Option<String>,
}

struct WebSocketSession {
    sender: mpsc::UnboundedSender<Message>,
    task: tauri::async_runtime::JoinHandle<()>,
}

struct AppState {
    client: Client,
    web_socket: Mutex<Option<WebSocketSession>>,
}

#[derive(Default)]
struct EmbeddedBackendSession {
    base_url: Option<String>,
    child: Option<CommandChild>,
    startup_error: Option<String>,
    manages_backend: bool,
}

#[derive(Default)]
struct EmbeddedBackendState {
    session: StandardMutex<EmbeddedBackendSession>,
}

impl AppState {
    fn new() -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECONDS))
            .build()
            .expect("HTTP 客户端配置必须有效");
        Self {
            client,
            web_socket: Mutex::new(None),
        }
    }
}

fn normalize_base_url(base_url: &str) -> Result<Url, CommandError> {
    let trimmed = base_url.trim().trim_end_matches('/');
    let mut url = Url::parse(trimmed)
        .map_err(|_| CommandError::new("invalid_server_url", "服务器地址格式无效"))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err(CommandError::new(
            "invalid_server_url",
            "服务器地址必须使用 http 或 https",
        ));
    }
    url.set_query(None);
    url.set_fragment(None);
    Ok(url)
}

fn endpoint_url(base_url: &str, path: &str) -> Result<Url, CommandError> {
    let base = normalize_base_url(base_url)?;
    base.join(path)
        .map_err(|_| CommandError::new("invalid_server_url", "无法生成接口地址"))
}

fn websocket_url(base_url: &str) -> Result<Url, CommandError> {
    let mut url = endpoint_url(base_url, "/ws")?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
        .map_err(|_| CommandError::new("invalid_server_url", "无法生成 WebSocket 地址"))?;
    Ok(url)
}

fn authorized_request(client: &Client, url: Url, access_token: &str) -> reqwest::RequestBuilder {
    client.get(url).bearer_auth(access_token)
}

fn extract_api_error(body: &str, fallback: &str) -> (String, String) {
    let Ok(value) = serde_json::from_str::<Value>(body) else {
        return ("request_failed".to_string(), fallback.to_string());
    };
    let Some(detail) = value.get("detail") else {
        return ("request_failed".to_string(), fallback.to_string());
    };
    if let Some(message) = detail.as_str() {
        return ("request_failed".to_string(), message.to_string());
    }
    let code = detail
        .get("code")
        .and_then(Value::as_str)
        .unwrap_or("request_failed");
    let message = detail
        .get("message")
        .and_then(Value::as_str)
        .unwrap_or(fallback);
    (code.to_string(), message.to_string())
}

async fn parse_response<T: DeserializeOwned>(
    response: Response,
    fallback: &str,
) -> Result<T, CommandError> {
    let status = response.status();
    let body = response.text().await.map_err(|_| {
        CommandError::with_status("invalid_response", "读取服务器响应失败", status)
    })?;
    if !status.is_success() {
        let (mut code, message) = extract_api_error(&body, fallback);
        if status == StatusCode::UNAUTHORIZED {
            code = "unauthorized".to_string();
        }
        return Err(CommandError::with_status(code, message, status));
    }
    serde_json::from_str(&body).map_err(|_| {
        CommandError::with_status("invalid_response", "服务器响应格式无效", status)
    })
}

async fn send_request(
    request: reqwest::RequestBuilder,
    failure_message: &str,
) -> Result<Response, CommandError> {
    request.send().await.map_err(|error| {
        let message = if error.is_timeout() {
            "连接服务器超时"
        } else if error.is_connect() {
            "无法连接服务器"
        } else {
            failure_message
        };
        CommandError::new("network_error", message)
    })
}

#[tauri::command]
async fn check_server(base_url: String, state: State<'_, AppState>) -> Result<(), CommandError> {
    let response = send_request(
        state.client.get(endpoint_url(&base_url, "/health/ready")?),
        "服务器检查失败",
    )
    .await?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(CommandError::with_status(
            "server_not_ready",
            "服务器尚未就绪",
            response.status(),
        ))
    }
}

#[tauri::command]
async fn get_embedded_server(
    backend_state: State<'_, EmbeddedBackendState>,
    app_state: State<'_, AppState>,
) -> Result<String, CommandError> {
    let (base_url, manages_backend) = {
        let session = backend_state
            .session
            .lock()
            .map_err(|_| CommandError::new("backend_error", "内置服务状态读取失败"))?;
        if let Some(error) = &session.startup_error {
            return Err(CommandError::new("backend_error", error.clone()));
        }
        (
            session.base_url.clone().ok_or_else(|| {
                CommandError::new("backend_error", "服务地址尚未完成初始化")
            })?,
            session.manages_backend,
        )
    };

    if !manages_backend {
        return Ok(base_url);
    }

    let health_url = endpoint_url(&base_url, "/health/ready")?;
    for _ in 0..EMBEDDED_BACKEND_START_ATTEMPTS {
        if let Ok(response) = app_state.client.get(health_url.clone()).send().await {
            if response.status().is_success() {
                return Ok(base_url);
            }
        }
        tokio::time::sleep(Duration::from_millis(
            EMBEDDED_BACKEND_RETRY_MILLISECONDS,
        ))
        .await;
    }
    Err(CommandError::new(
        "backend_start_timeout",
        "内置服务启动超时，请重新启动客户端",
    ))
}

#[tauri::command]
async fn register_user(
    base_url: String,
    username: String,
    password: String,
    state: State<'_, AppState>,
) -> Result<UserIdentity, CommandError> {
    let response = send_request(
        state
            .client
            .post(endpoint_url(&base_url, "/auth/register")?)
            .json(&serde_json::json!({
                "username": username,
                "password": password,
            })),
        "注册请求失败",
    )
    .await?;
    parse_response(response, "注册失败").await
}

#[tauri::command]
async fn login(
    base_url: String,
    username: String,
    password: String,
    state: State<'_, AppState>,
) -> Result<AccessToken, CommandError> {
    let response = send_request(
        state
            .client
            .post(endpoint_url(&base_url, "/auth/token")?)
            .form(&[("username", username), ("password", password)]),
        "登录请求失败",
    )
    .await?;
    parse_response(response, "登录失败").await
}

#[tauri::command]
async fn get_current_user(
    base_url: String,
    access_token: String,
    state: State<'_, AppState>,
) -> Result<UserIdentity, CommandError> {
    let response = send_request(
        authorized_request(
            &state.client,
            endpoint_url(&base_url, "/auth/me")?,
            &access_token,
        ),
        "身份查询失败",
    )
    .await?;
    parse_response(response, "身份查询失败").await
}

#[tauri::command]
async fn create_conversation(
    base_url: String,
    access_token: String,
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<Conversation, CommandError> {
    let response = send_request(
        state
            .client
            .post(endpoint_url(&base_url, "/conversations")?)
            .bearer_auth(access_token)
            .json(&serde_json::json!({"peer_id": peer_id})),
        "会话请求失败",
    )
    .await?;
    parse_response(response, "无法创建或打开会话").await
}

#[tauri::command]
async fn get_message_history(
    base_url: String,
    access_token: String,
    conversation_id: String,
    cursor: Option<String>,
    limit: u16,
    state: State<'_, AppState>,
) -> Result<HistoryPage, CommandError> {
    if !(1..=100).contains(&limit) {
        return Err(CommandError::new(
            "invalid_history_query",
            "历史消息页大小必须在 1 到 100 之间",
        ));
    }
    let path = format!("/conversations/{conversation_id}/messages");
    let mut url = endpoint_url(&base_url, &path)?;
    {
        let mut query = url.query_pairs_mut();
        query.append_pair("limit", &limit.to_string());
        if let Some(value) = cursor {
            query.append_pair("cursor", &value);
        }
    }
    let response = send_request(
        authorized_request(&state.client, url, &access_token),
        "历史消息查询失败",
    )
    .await?;
    parse_response(response, "历史消息查询失败").await
}

#[tauri::command]
async fn connect_websocket(
    app: AppHandle,
    base_url: String,
    access_token: String,
    state: State<'_, AppState>,
) -> Result<(), CommandError> {
    let mut guard = state.web_socket.lock().await;
    if let Some(previous) = guard.take() {
        let _ = previous.sender.send(Message::Close(None));
        previous.task.abort();
    }

    let mut request = websocket_url(&base_url)?
        .as_str()
        .into_client_request()
        .map_err(|_| CommandError::new("websocket_error", "WebSocket 地址无效"))?;
    let authorization = HeaderValue::from_str(&format!("Bearer {access_token}"))
        .map_err(|_| CommandError::new("unauthorized", "访问令牌格式无效"))?;
    request.headers_mut().insert(AUTHORIZATION, authorization);

    let (socket, _) = tokio_tungstenite::connect_async(request)
        .await
        .map_err(|error| {
            CommandError::new(
                "websocket_error",
                format!("WebSocket 连接失败：{error}"),
            )
        })?;
    let (mut writer, mut reader) = socket.split();
    let (sender, mut receiver) = mpsc::unbounded_channel::<Message>();

    app.emit(
        "websocket-status",
        WebSocketStatus {
            state: "connected",
            code: None,
            reason: None,
        },
    )
    .map_err(|_| CommandError::new("event_error", "连接状态通知失败"))?;

    let event_app = app.clone();
    let task = tauri::async_runtime::spawn(async move {
        let mut close_code = None;
        let mut close_reason = None;
        loop {
            tokio::select! {
                outgoing = receiver.recv() => {
                    let Some(message) = outgoing else {
                        break;
                    };
                    if writer.send(message).await.is_err() {
                        close_reason = Some("发送通道已断开".to_string());
                        break;
                    }
                }
                incoming = reader.next() => {
                    match incoming {
                        Some(Ok(Message::Text(text))) => {
                            match serde_json::from_str::<Value>(text.as_ref()) {
                                Ok(payload) => {
                                    let _ = event_app.emit("chat-event", payload);
                                }
                                Err(_) => {
                                    close_reason = Some("服务器发送了无效消息".to_string());
                                    break;
                                }
                            }
                        }
                        Some(Ok(Message::Ping(payload))) => {
                            if writer.send(Message::Pong(payload)).await.is_err() {
                                break;
                            }
                        }
                        Some(Ok(Message::Close(frame))) => {
                            if let Some(frame) = frame {
                                close_code = Some(frame.code.into());
                                if !frame.reason.is_empty() {
                                    close_reason = Some(frame.reason.to_string());
                                }
                            }
                            break;
                        }
                        Some(Ok(_)) => {}
                        Some(Err(error)) => {
                            close_reason = Some(format!("连接异常：{error}"));
                            break;
                        }
                        None => break,
                    }
                }
            }
        }
        let _ = event_app.emit(
            "websocket-status",
            WebSocketStatus {
                state: "disconnected",
                code: close_code,
                reason: close_reason,
            },
        );
    });

    *guard = Some(WebSocketSession { sender, task });
    Ok(())
}

#[tauri::command]
async fn send_websocket_command(
    payload: Value,
    state: State<'_, AppState>,
) -> Result<(), CommandError> {
    if !payload.is_object() || payload.get("type").and_then(Value::as_str).is_none() {
        return Err(CommandError::new(
            "invalid_message",
            "WebSocket 命令必须包含 type 字段",
        ));
    }
    let text = serde_json::to_string(&payload)
        .map_err(|_| CommandError::new("invalid_message", "命令序列化失败"))?;
    let guard = state.web_socket.lock().await;
    let Some(session) = guard.as_ref() else {
        return Err(CommandError::new("websocket_disconnected", "实时连接尚未建立"));
    };
    session
        .sender
        .send(Message::Text(text.into()))
        .map_err(|_| CommandError::new("websocket_disconnected", "实时连接已经断开"))
}

#[tauri::command]
async fn disconnect_websocket(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), CommandError> {
    let mut guard = state.web_socket.lock().await;
    if let Some(session) = guard.take() {
        let _ = session.sender.send(Message::Close(None));
        session.task.abort();
    }
    app.emit(
        "websocket-status",
        WebSocketStatus {
            state: "disconnected",
            code: None,
            reason: Some("用户主动断开".to_string()),
        },
    )
    .map_err(|_| CommandError::new("event_error", "连接状态通知失败"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState::new())
        .manage(EmbeddedBackendState::default())
        .setup(|app| {
            if app.config().identifier == STANDALONE_APP_IDENTIFIER {
                if let Err(error) = start_embedded_backend(app.handle()) {
                    let state = app.state::<EmbeddedBackendState>();
                    if let Ok(mut session) = state.session.lock() {
                        session.startup_error = Some(error.message);
                    };
                }
            } else {
                let state = app.state::<EmbeddedBackendState>();
                if let Ok(mut session) = state.session.lock() {
                    session.base_url = Some(EXTERNAL_SERVER_URL.to_string());
                    session.manages_backend = false;
                };
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_embedded_server,
            check_server,
            register_user,
            login,
            get_current_user,
            create_conversation,
            get_message_history,
            connect_websocket,
            send_websocket_command,
            disconnect_websocket,
        ])
        .build(tauri::generate_context!())
        .expect("构建 Tauri 桌面客户端失败");
    application.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_embedded_backend(app);
        }
    });
}

fn start_embedded_backend(app: &AppHandle) -> Result<(), CommandError> {
    let port = reserve_loopback_port()?;
    let data_directory = app
        .path()
        .app_data_dir()
        .map_err(|_| CommandError::new("backend_error", "无法定位应用数据目录"))?
        .join("backend");
    std::fs::create_dir_all(&data_directory)
        .map_err(|_| CommandError::new("backend_error", "无法创建应用数据目录"))?;
    let arguments = vec![
        OsString::from("--host"),
        OsString::from("127.0.0.1"),
        OsString::from("--port"),
        OsString::from(port.to_string()),
        OsString::from("--data-dir"),
        data_directory.into_os_string(),
        OsString::from("--parent-pid"),
        OsString::from(std::process::id().to_string()),
    ];
    let (mut events, child) = app
        .shell()
        .sidecar("bidirectional-backend")
        .map_err(|error| {
            CommandError::new("backend_error", format!("无法加载内置服务：{error}"))
        })?
        .args(arguments)
        .spawn()
        .map_err(|error| {
            CommandError::new("backend_error", format!("无法启动内置服务：{error}"))
        })?;
    let base_url = format!("http://127.0.0.1:{port}");
    {
        let state = app.state::<EmbeddedBackendState>();
        let mut session = state
            .session
            .lock()
            .map_err(|_| CommandError::new("backend_error", "内置服务状态写入失败"))?;
        session.base_url = Some(base_url);
        session.child = Some(child);
        session.startup_error = None;
        session.manages_backend = true;
    }

    let event_app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            if let CommandEvent::Terminated(payload) = event {
                let reason = format!("内置服务已退出，退出码：{:?}", payload.code);
                let state = event_app.state::<EmbeddedBackendState>();
                if let Ok(mut session) = state.session.lock() {
                    session.startup_error = Some(reason.clone());
                }
                let _ = event_app.emit("embedded-backend-error", reason);
                break;
            }
        }
    });
    Ok(())
}

fn stop_embedded_backend(app: &AppHandle) {
    let state = app.state::<EmbeddedBackendState>();
    if let Ok(mut session) = state.session.lock() {
        if let Some(child) = session.child.take() {
            let _ = child.kill();
        }
    };
}

fn reserve_loopback_port() -> Result<u16, CommandError> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|_| CommandError::new("backend_error", "无法分配本地服务端口"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|_| CommandError::new("backend_error", "无法读取本地服务端口"))
}

#[cfg(test)]
mod tests {
    use super::{
        extract_api_error, normalize_base_url, reserve_loopback_port, websocket_url,
    };

    #[test]
    fn normalizes_http_base_url() {
        let url = normalize_base_url(" http://127.0.0.1:8000/ ").unwrap();
        assert_eq!(url.as_str(), "http://127.0.0.1:8000/");
    }

    #[test]
    fn converts_secure_http_to_websocket() {
        let url = websocket_url("https://chat.example.com/api").unwrap();
        assert_eq!(url.as_str(), "wss://chat.example.com/ws");
    }

    #[test]
    fn extracts_structured_fastapi_error() {
        let (code, message) = extract_api_error(
            r#"{"detail":{"code":"conversation_unavailable","message":"无法访问"}}"#,
            "请求失败",
        );
        assert_eq!(code, "conversation_unavailable");
        assert_eq!(message, "无法访问");
    }

    #[test]
    fn reserves_available_loopback_port() {
        let port = reserve_loopback_port().unwrap();
        assert!(port > 0);
    }
}

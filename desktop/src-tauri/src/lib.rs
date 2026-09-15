use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use http::header::{HeaderValue, AUTHORIZATION};
use reqwest::{Client, Response, StatusCode};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, State};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};
use url::Url;

const REQUEST_TIMEOUT_SECONDS: u64 = 15;

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
    created_at: String,
    created: bool,
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
    tauri::Builder::default()
        .manage(AppState::new())
        .invoke_handler(tauri::generate_handler![
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
        .run(tauri::generate_context!())
        .expect("启动 Tauri 桌面客户端失败");
}

#[cfg(test)]
mod tests {
    use super::{extract_api_error, normalize_base_url, websocket_url};

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
}

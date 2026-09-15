<script setup lang="ts">
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import { desktopBridge, normalizeCommandError } from "./bridge";
import {
  fromHistoryMessage,
  fromMessageEvent,
  getLastServerMessageId,
  mergeMessages,
} from "./messageState";
import type {
  ChatMessage,
  Conversation,
  ServerEvent,
  SocketStatusEvent,
  UserIdentity,
} from "./types";

type AuthMode = "login" | "register";
type SocketState = "idle" | "connecting" | "connected" | "disconnected";

const MAX_HISTORY_PAGES = 50;
const DEFAULT_SERVER_URL = "http://127.0.0.1:8000";

const serverUrl = ref(localStorage.getItem("chat.serverUrl") ?? DEFAULT_SERVER_URL);
const authMode = ref<AuthMode>("login");
const username = ref("");
const password = ref("");
const authBusy = ref(false);
const authError = ref("");

const accessToken = ref("");
const tokenExpiresAt = ref("");
const currentUser = ref<UserIdentity | null>(null);
const socketState = ref<SocketState>("idle");
const socketReason = ref("");
const manualDisconnect = ref(false);
const reconnectDelay = ref(1000);
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

const conversations = ref<Conversation[]>([]);
const activeConversationId = ref<string | null>(null);
const messagesByConversation = ref<Record<string, ChatMessage[]>>({});
const historyLoading = ref(false);
const conversationSearch = ref("");
const newConversationOpen = ref(false);
const peerId = ref("");
const conversationBusy = ref(false);
const conversationError = ref("");

const draft = ref("");
const sending = ref(false);
const notice = ref("");
const messageList = ref<HTMLElement | null>(null);
let noticeTimer: ReturnType<typeof setTimeout> | null = null;
const unlistenCallbacks: UnlistenFn[] = [];

const isAuthenticated = computed(() => currentUser.value !== null && accessToken.value !== "");
const activeConversation = computed(
  () =>
    conversations.value.find(
      (conversation) => conversation.conversation_id === activeConversationId.value,
    ) ?? null,
);
const activeMessages = computed(() => {
  if (!activeConversationId.value) {
    return [];
  }
  return messagesByConversation.value[activeConversationId.value] ?? [];
});
const filteredConversations = computed(() => {
  const query = conversationSearch.value.trim().toLowerCase();
  if (!query) {
    return conversations.value;
  }
  return conversations.value.filter((conversation) => {
    const peer = getPeerId(conversation).toLowerCase();
    return peer.includes(query) || conversation.conversation_id.toLowerCase().includes(query);
  });
});
const connectionLabel = computed(() => {
  const labels: Record<SocketState, string> = {
    idle: "未连接",
    connecting: "连接中",
    connected: "实时在线",
    disconnected: "正在重连",
  };
  return labels[socketState.value];
});

function getPeerId(conversation: Conversation): string {
  return (
    conversation.member_ids.find((memberId) => memberId !== currentUser.value?.user_id) ??
    conversation.member_ids[0] ??
    "未知用户"
  );
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function avatarLabel(value: string): string {
  return value.replaceAll("-", "").slice(0, 2).toUpperCase() || "ID";
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function showNotice(message: string): void {
  notice.value = message;
  if (noticeTimer) {
    clearTimeout(noticeTimer);
  }
  noticeTimer = setTimeout(() => {
    notice.value = "";
  }, 3200);
}

function persistConversations(): void {
  if (!currentUser.value) {
    return;
  }
  localStorage.setItem(
    `chat.conversations.${currentUser.value.user_id}`,
    JSON.stringify(conversations.value),
  );
}

function restoreConversations(): void {
  if (!currentUser.value) {
    return;
  }
  const stored = localStorage.getItem(`chat.conversations.${currentUser.value.user_id}`);
  if (!stored) {
    conversations.value = [];
    return;
  }
  try {
    const parsed = JSON.parse(stored) as Conversation[];
    conversations.value = Array.isArray(parsed) ? parsed : [];
  } catch {
    conversations.value = [];
  }
}

function addConversation(conversation: Conversation): void {
  const existing = conversations.value.findIndex(
    (item) => item.conversation_id === conversation.conversation_id,
  );
  if (existing >= 0) {
    conversations.value.splice(existing, 1, conversation);
  } else {
    conversations.value.unshift(conversation);
  }
  persistConversations();
}

function ensureConversationForMessage(event: {
  conversation_id: string;
  sender_id: string;
  recipient_id: string;
  sent_at: string;
}): void {
  if (conversations.value.some((item) => item.conversation_id === event.conversation_id)) {
    return;
  }
  addConversation({
    conversation_id: event.conversation_id,
    member_ids: [event.sender_id, event.recipient_id],
    created_at: event.sent_at,
    created: false,
  });
}

function updateConversationMessages(conversationId: string, incoming: ChatMessage[]): void {
  const existing = messagesByConversation.value[conversationId] ?? [];
  messagesByConversation.value[conversationId] = mergeMessages(existing, incoming);
  if (conversationId === activeConversationId.value) {
    void scrollToBottom();
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (messageList.value) {
    messageList.value.scrollTop = messageList.value.scrollHeight;
  }
}

async function submitAuth(): Promise<void> {
  authError.value = "";
  authBusy.value = true;
  const normalizedServerUrl = serverUrl.value.trim().replace(/\/$/, "");
  try {
    await desktopBridge.checkServer(normalizedServerUrl);
    if (authMode.value === "register") {
      await desktopBridge.register(normalizedServerUrl, username.value, password.value);
    }
    const token = await desktopBridge.login(
      normalizedServerUrl,
      username.value,
      password.value,
    );
    const identity = await desktopBridge.getCurrentUser(
      normalizedServerUrl,
      token.access_token,
    );
    serverUrl.value = normalizedServerUrl;
    localStorage.setItem("chat.serverUrl", normalizedServerUrl);
    accessToken.value = token.access_token;
    tokenExpiresAt.value = token.expires_at;
    currentUser.value = identity;
    password.value = "";
    restoreConversations();
    manualDisconnect.value = false;
    await connectSocket();
  } catch (error) {
    authError.value = normalizeCommandError(error).message;
  } finally {
    authBusy.value = false;
  }
}

async function connectSocket(): Promise<void> {
  if (!accessToken.value || manualDisconnect.value || socketState.value === "connecting") {
    return;
  }
  socketState.value = "connecting";
  socketReason.value = "";
  try {
    await desktopBridge.connectWebSocket(serverUrl.value, accessToken.value);
  } catch (error) {
    socketState.value = "disconnected";
    socketReason.value = normalizeCommandError(error).message;
    scheduleReconnect();
  }
}

function scheduleReconnect(): void {
  if (manualDisconnect.value || !isAuthenticated.value || reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectSocket();
  }, reconnectDelay.value);
  reconnectDelay.value = Math.min(reconnectDelay.value * 2, 15_000);
}

async function endSession(message = ""): Promise<void> {
  manualDisconnect.value = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  try {
    await desktopBridge.disconnectWebSocket();
  } catch {
    // 本地状态仍需退出，断开失败不应阻塞注销。
  }
  accessToken.value = "";
  tokenExpiresAt.value = "";
  currentUser.value = null;
  socketState.value = "idle";
  activeConversationId.value = null;
  conversations.value = [];
  messagesByConversation.value = {};
  if (message) {
    authError.value = message;
  }
}

async function createNewConversation(): Promise<void> {
  if (!currentUser.value || !accessToken.value || !peerId.value.trim()) {
    return;
  }
  conversationBusy.value = true;
  conversationError.value = "";
  try {
    const conversation = await desktopBridge.createConversation(
      serverUrl.value,
      accessToken.value,
      peerId.value.trim(),
    );
    addConversation(conversation);
    peerId.value = "";
    newConversationOpen.value = false;
    await openConversation(conversation);
  } catch (error) {
    const commandError = normalizeCommandError(error);
    if (commandError.status === 401) {
      await endSession("登录已过期，请重新登录");
      return;
    }
    conversationError.value = commandError.message;
  } finally {
    conversationBusy.value = false;
  }
}

async function openConversation(conversation: Conversation): Promise<void> {
  activeConversationId.value = conversation.conversation_id;
  newConversationOpen.value = false;
  if (!messagesByConversation.value[conversation.conversation_id]) {
    await loadHistory(conversation.conversation_id);
  } else {
    await scrollToBottom();
  }
  if (socketState.value === "connected") {
    await syncConversation(conversation.conversation_id);
    await acknowledgeLatest(conversation.conversation_id, "read");
  }
}

async function loadHistory(conversationId: string): Promise<void> {
  if (!accessToken.value) {
    return;
  }
  historyLoading.value = true;
  let cursor: string | null = null;
  let pageCount = 0;
  let hasMore = false;
  const historyMessages: ChatMessage[] = [];
  try {
    do {
      const page = await desktopBridge.getMessageHistory(
        serverUrl.value,
        accessToken.value,
        conversationId,
        cursor,
      );
      historyMessages.push(...page.messages.map(fromHistoryMessage));
      cursor = page.next_cursor;
      hasMore = page.has_more;
      pageCount += 1;
    } while (hasMore && cursor && pageCount < MAX_HISTORY_PAGES);
    updateConversationMessages(conversationId, historyMessages);
    if (hasMore) {
      showNotice("历史消息较多，当前仅加载前 5000 条数据");
    }
    if (socketState.value === "connected") {
      await acknowledgeLatest(conversationId, "delivered");
    }
  } catch (error) {
    const commandError = normalizeCommandError(error);
    if (commandError.status === 401) {
      await endSession("登录已过期，请重新登录");
    } else {
      showNotice(commandError.message);
    }
  } finally {
    historyLoading.value = false;
  }
}

async function sendMessage(): Promise<void> {
  const content = draft.value.trim();
  const conversation = activeConversation.value;
  const user = currentUser.value;
  if (!content || !conversation || !user || sending.value) {
    return;
  }
  if (socketState.value !== "connected") {
    showNotice("实时连接尚未恢复，请稍后再试");
    return;
  }
  const clientMessageId = crypto.randomUUID();
  const optimistic: ChatMessage = {
    serverMessageId: null,
    clientMessageId,
    conversationId: conversation.conversation_id,
    senderId: user.user_id,
    recipientId: getPeerId(conversation),
    content,
    sentAt: new Date().toISOString(),
    status: "sending",
  };
  draft.value = "";
  sending.value = true;
  updateConversationMessages(conversation.conversation_id, [optimistic]);
  try {
    await desktopBridge.sendWebSocketCommand({
      type: "send_message",
      conversation_id: conversation.conversation_id,
      content,
      client_message_id: clientMessageId,
    });
  } catch (error) {
    markMessageFailed(clientMessageId);
    showNotice(normalizeCommandError(error).message);
  } finally {
    sending.value = false;
  }
}

function markMessageFailed(clientMessageId: string): void {
  for (const [conversationId, messages] of Object.entries(messagesByConversation.value)) {
    const message = messages.find((item) => item.clientMessageId === clientMessageId);
    if (message) {
      updateConversationMessages(conversationId, [{ ...message, status: "failed" }]);
      return;
    }
  }
}

async function acknowledgeLatest(
  conversationId: string,
  positionType: "delivered" | "read",
): Promise<void> {
  const messageId = getLastServerMessageId(messagesByConversation.value[conversationId] ?? []);
  if (!messageId || socketState.value !== "connected") {
    return;
  }
  try {
    await desktopBridge.sendWebSocketCommand({
      type: "acknowledge_position",
      conversation_id: conversationId,
      position_type: positionType,
      message_id: messageId,
    });
  } catch {
    // 累计位置可在下次同步时再次推进。
  }
}

async function syncConversation(conversationId: string): Promise<void> {
  const afterMessageId = getLastServerMessageId(
    messagesByConversation.value[conversationId] ?? [],
  );
  try {
    await desktopBridge.sendWebSocketCommand({
      type: "sync_messages",
      conversation_id: conversationId,
      after_message_id: afterMessageId,
      limit: 100,
    });
  } catch {
    // 连接状态事件会触发重连，恢复后会再次同步。
  }
}

async function handleServerEvent(event: ServerEvent): Promise<void> {
  if (event.type === "message") {
    ensureConversationForMessage(event);
    updateConversationMessages(event.conversation_id, [fromMessageEvent(event)]);
    await acknowledgeLatest(event.conversation_id, "delivered");
    if (activeConversationId.value === event.conversation_id) {
      await acknowledgeLatest(event.conversation_id, "read");
    } else {
      showNotice("收到一条新消息");
    }
    return;
  }
  if (event.type === "accepted") {
    const messages = messagesByConversation.value[event.conversation_id] ?? [];
    const message = messages.find((item) => item.clientMessageId === event.client_message_id);
    if (message) {
      updateConversationMessages(event.conversation_id, [
        {
          ...message,
          serverMessageId: event.server_message_id,
          status: "accepted",
          pushStatus: event.push_status,
        },
      ]);
    }
    return;
  }
  if (event.type === "error") {
    if (event.client_message_id) {
      markMessageFailed(event.client_message_id);
    }
    showNotice(event.message);
    return;
  }
  if (event.type === "sync_result") {
    const synchronized = event.messages.map(fromMessageEvent);
    if (synchronized.length > 0) {
      updateConversationMessages(event.conversation_id, synchronized);
      await acknowledgeLatest(event.conversation_id, "delivered");
      if (activeConversationId.value === event.conversation_id) {
        await acknowledgeLatest(event.conversation_id, "read");
      }
    }
    if (event.has_more && synchronized.length > 0) {
      await syncConversation(event.conversation_id);
    }
  }
}

async function handleSocketStatus(status: SocketStatusEvent): Promise<void> {
  if (status.state === "connected") {
    socketState.value = "connected";
    socketReason.value = "";
    reconnectDelay.value = 1000;
    if (activeConversationId.value) {
      await syncConversation(activeConversationId.value);
    }
    return;
  }
  if (manualDisconnect.value) {
    socketState.value = "idle";
    return;
  }
  socketState.value = "disconnected";
  socketReason.value = status.reason ?? "实时连接已断开";
  if (status.code === 4401) {
    await endSession("登录已过期，请重新登录");
    return;
  }
  scheduleReconnect();
}

async function copyOwnId(): Promise<void> {
  if (!currentUser.value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(currentUser.value.user_id);
    showNotice("用户 ID 已复制");
  } catch {
    showNotice("复制失败，请手动选择用户 ID");
  }
}

function switchAuthMode(mode: AuthMode): void {
  authMode.value = mode;
  authError.value = "";
}

function openNewConversation(): void {
  conversationError.value = "";
  peerId.value = "";
  newConversationOpen.value = true;
}

onMounted(async () => {
  unlistenCallbacks.push(
    await listen<ServerEvent>("chat-event", (event) => {
      void handleServerEvent(event.payload);
    }),
  );
  unlistenCallbacks.push(
    await listen<SocketStatusEvent>("websocket-status", (event) => {
      void handleSocketStatus(event.payload);
    }),
  );
});

onBeforeUnmount(() => {
  manualDisconnect.value = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
  }
  if (noticeTimer) {
    clearTimeout(noticeTimer);
  }
  for (const unlisten of unlistenCallbacks) {
    unlisten();
  }
  void desktopBridge.disconnectWebSocket();
});
</script>

<template>
  <main v-if="!isAuthenticated" class="auth-shell">
    <section class="auth-story" aria-label="产品介绍">
      <div class="brand-mark" aria-hidden="true">
        <span></span>
        <span></span>
      </div>
      <div class="story-copy">
        <p class="eyebrow">Bidirectional Communication</p>
        <h1>让每一次对话，<br />都稳稳抵达。</h1>
        <p class="story-description">
          一个专注、可靠的桌面通信空间。实时收发、断线补偿和清晰的消息状态，
          都藏在安静的界面之下。
        </p>
      </div>
      <div class="story-signal" aria-hidden="true">
        <span class="signal-line"></span>
        <span class="signal-dot signal-dot-start"></span>
        <span class="signal-dot signal-dot-end"></span>
        <span class="signal-label">端到端通信链路</span>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <div class="auth-heading">
          <p class="eyebrow">桌面客户端</p>
          <h2>{{ authMode === "login" ? "欢迎回来" : "创建你的账户" }}</h2>
          <p>{{ authMode === "login" ? "登录后继续你的对话" : "注册后将自动登录" }}</p>
        </div>

        <div class="auth-switch" role="tablist" aria-label="认证方式">
          <button
            :class="{ active: authMode === 'login' }"
            type="button"
            role="tab"
            @click="switchAuthMode('login')"
          >
            登录
          </button>
          <button
            :class="{ active: authMode === 'register' }"
            type="button"
            role="tab"
            @click="switchAuthMode('register')"
          >
            注册
          </button>
        </div>

        <form class="auth-form" @submit.prevent="submitAuth">
          <label>
            <span>服务器地址</span>
            <input
              v-model="serverUrl"
              type="url"
              inputmode="url"
              placeholder="http://127.0.0.1:8000"
              required
            />
          </label>
          <label>
            <span>用户名</span>
            <input
              v-model="username"
              type="text"
              autocomplete="username"
              minlength="3"
              maxlength="32"
              placeholder="输入用户名"
              required
            />
          </label>
          <label>
            <span>密码</span>
            <input
              v-model="password"
              type="password"
              :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'"
              minlength="8"
              maxlength="128"
              placeholder="至少 8 个字符"
              required
            />
          </label>
          <p v-if="authError" class="form-error" role="alert">{{ authError }}</p>
          <button class="primary-button" type="submit" :disabled="authBusy">
            <span v-if="authBusy" class="button-loader" aria-hidden="true"></span>
            {{ authBusy ? "正在连接" : authMode === "login" ? "进入对话" : "注册并进入" }}
          </button>
        </form>

        <p class="privacy-note">访问令牌仅保存在本次运行内存中，退出后自动清除。</p>
      </div>
    </section>
  </main>

  <main v-else class="app-shell">
    <aside class="sidebar">
      <header class="sidebar-header">
        <div class="compact-brand">
          <div class="brand-mark small" aria-hidden="true"><span></span><span></span></div>
          <div>
            <strong>双向通信</strong>
            <span>Desktop</span>
          </div>
        </div>
        <button class="icon-button" type="button" title="新建会话" @click="openNewConversation">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </header>

      <div class="search-box">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" />
          <path d="m16 16 4 4" />
        </svg>
        <input v-model="conversationSearch" type="search" placeholder="搜索会话或 ID" />
      </div>

      <div class="conversation-heading">
        <span>最近对话</span>
        <span>{{ conversations.length }}</span>
      </div>

      <nav class="conversation-list" aria-label="会话列表">
        <button
          v-for="conversation in filteredConversations"
          :key="conversation.conversation_id"
          class="conversation-item"
          :class="{ active: activeConversationId === conversation.conversation_id }"
          type="button"
          @click="openConversation(conversation)"
        >
          <span class="avatar">{{ avatarLabel(getPeerId(conversation)) }}</span>
          <span class="conversation-copy">
            <strong>{{ shortId(getPeerId(conversation)) }}</strong>
            <span>
              {{
                messagesByConversation[conversation.conversation_id]?.at(-1)?.content ??
                "打开会话查看消息"
              }}
            </span>
          </span>
          <time>{{ formatTime(conversation.created_at) }}</time>
        </button>

        <div v-if="filteredConversations.length === 0" class="empty-conversations">
          <div class="empty-lines" aria-hidden="true"><span></span><span></span><span></span></div>
          <p>{{ conversations.length ? "没有匹配的会话" : "还没有会话" }}</p>
          <button v-if="!conversations.length" type="button" @click="openNewConversation">
            发起第一次对话
          </button>
        </div>
      </nav>

      <footer class="profile-card">
        <span class="avatar user-avatar">{{ avatarLabel(currentUser?.username ?? "") }}</span>
        <span class="profile-copy">
          <strong>{{ currentUser?.username }}</strong>
          <button type="button" title="复制完整用户 ID" @click="copyOwnId">
            {{ shortId(currentUser?.user_id ?? "") }}
          </button>
        </span>
        <button class="logout-button" type="button" title="退出登录" @click="endSession()">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4M14 8l4 4-4 4M18 12H9" />
          </svg>
        </button>
      </footer>
    </aside>

    <section class="chat-panel">
      <template v-if="activeConversation">
        <header class="chat-header">
          <div class="chat-person">
            <span class="avatar large">{{ avatarLabel(getPeerId(activeConversation)) }}</span>
            <div>
              <strong>{{ shortId(getPeerId(activeConversation)) }}</strong>
              <span class="connection-state" :class="socketState">
                <i></i>{{ connectionLabel }}
              </span>
            </div>
          </div>
          <div class="conversation-meta">
            <span>会话</span>
            <code>{{ shortId(activeConversation.conversation_id) }}</code>
          </div>
        </header>

        <div ref="messageList" class="message-list" aria-live="polite">
          <div v-if="historyLoading" class="history-loader">
            <span></span>正在读取历史消息
          </div>
          <div v-if="!historyLoading && activeMessages.length === 0" class="empty-chat">
            <div class="empty-chat-mark" aria-hidden="true">
              <span></span><span></span><span></span>
            </div>
            <h2>从一句你好开始</h2>
            <p>消息会实时送达，连接中断后也会自动补齐。</p>
          </div>
          <article
            v-for="message in activeMessages"
            :key="message.clientMessageId"
            class="message-row"
            :class="{ own: message.senderId === currentUser?.user_id }"
          >
            <div class="message-bubble">
              <p>{{ message.content }}</p>
              <div class="message-details">
                <time>{{ formatTime(message.sentAt) }}</time>
                <span v-if="message.senderId === currentUser?.user_id" :class="message.status">
                  {{
                    message.status === "sending"
                      ? "发送中"
                      : message.status === "failed"
                        ? "发送失败"
                        : "已保存"
                  }}
                </span>
              </div>
            </div>
          </article>
        </div>

        <footer class="composer-wrap">
          <form class="composer" @submit.prevent="sendMessage">
            <textarea
              v-model="draft"
              rows="1"
              maxlength="2000"
              placeholder="输入消息，Enter 发送，Shift + Enter 换行"
              @keydown.enter.exact.prevent="sendMessage"
            ></textarea>
            <span class="character-count">{{ draft.length }}/2000</span>
            <button
              class="send-button"
              type="submit"
              :disabled="!draft.trim() || sending || socketState !== 'connected'"
              title="发送消息"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m4 5 16 7-16 7 3-7-3-7Z" />
                <path d="M7 12h13" />
              </svg>
            </button>
          </form>
          <p v-if="socketReason && socketState !== 'connected'" class="socket-reason">
            {{ socketReason }}，客户端将自动重试
          </p>
        </footer>
      </template>

      <div v-else class="welcome-panel">
        <div class="welcome-art" aria-hidden="true">
          <span class="orbit orbit-one"></span>
          <span class="orbit orbit-two"></span>
          <span class="welcome-node node-one"></span>
          <span class="welcome-node node-two"></span>
          <span class="welcome-link"></span>
        </div>
        <p class="eyebrow">Ready to connect</p>
        <h1>选择一个会话，<br />或开始新的连接。</h1>
        <p>使用对方的用户 ID 建立一对一会话。</p>
        <button class="secondary-button" type="button" @click="openNewConversation">
          新建会话
        </button>
      </div>
    </section>

    <div v-if="newConversationOpen" class="modal-backdrop" @click.self="newConversationOpen = false">
      <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <button
          class="dialog-close"
          type="button"
          aria-label="关闭"
          @click="newConversationOpen = false"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
        <p class="eyebrow">New connection</p>
        <h2 id="dialog-title">发起一对一会话</h2>
        <p>输入对方的完整用户 ID。相同的两位用户始终复用同一个会话。</p>
        <form @submit.prevent="createNewConversation">
          <label>
            <span>对方用户 ID</span>
            <input
              v-model="peerId"
              type="text"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              required
              autofocus
            />
          </label>
          <p v-if="conversationError" class="form-error" role="alert">
            {{ conversationError }}
          </p>
          <button class="primary-button" type="submit" :disabled="conversationBusy">
            {{ conversationBusy ? "正在创建" : "打开会话" }}
          </button>
        </form>
      </section>
    </div>

    <div v-if="notice" class="toast" role="status">{{ notice }}</div>
  </main>
</template>

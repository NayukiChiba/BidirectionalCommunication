import { invoke } from "@tauri-apps/api/core";

import type {
  AccessToken,
  CommandError,
  Conversation,
  HistoryPage,
  UserIdentity,
} from "./types";

export function normalizeCommandError(error: unknown): CommandError {
  if (typeof error === "object" && error !== null) {
    const candidate = error as Partial<CommandError>;
    if (typeof candidate.message === "string") {
      return {
        code: typeof candidate.code === "string" ? candidate.code : "unknown_error",
        message: candidate.message,
        status: typeof candidate.status === "number" ? candidate.status : undefined,
      };
    }
  }
  return {
    code: "unknown_error",
    message: typeof error === "string" ? error : "发生未知错误",
  };
}

export const desktopBridge = {
  getEmbeddedServer(): Promise<string> {
    return invoke("get_embedded_server");
  },

  checkServer(baseUrl: string): Promise<void> {
    return invoke("check_server", { baseUrl });
  },

  register(
    baseUrl: string,
    username: string,
    password: string,
  ): Promise<UserIdentity> {
    return invoke("register_user", { baseUrl, username, password });
  },

  login(baseUrl: string, username: string, password: string): Promise<AccessToken> {
    return invoke("login", { baseUrl, username, password });
  },

  getCurrentUser(baseUrl: string, accessToken: string): Promise<UserIdentity> {
    return invoke("get_current_user", { baseUrl, accessToken });
  },

  createConversation(
    baseUrl: string,
    accessToken: string,
    peerId: string,
  ): Promise<Conversation> {
    return invoke("create_conversation", { baseUrl, accessToken, peerId });
  },

  getMessageHistory(
    baseUrl: string,
    accessToken: string,
    conversationId: string,
    cursor: string | null,
    limit = 100,
  ): Promise<HistoryPage> {
    return invoke("get_message_history", {
      baseUrl,
      accessToken,
      conversationId,
      cursor,
      limit,
    });
  },

  connectWebSocket(baseUrl: string, accessToken: string): Promise<void> {
    return invoke("connect_websocket", { baseUrl, accessToken });
  },

  sendWebSocketCommand(payload: Record<string, unknown>): Promise<void> {
    return invoke("send_websocket_command", { payload });
  },

  disconnectWebSocket(): Promise<void> {
    return invoke("disconnect_websocket");
  },
};

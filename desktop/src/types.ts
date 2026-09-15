export interface CommandError {
  code: string;
  message: string;
  status?: number;
}

export interface UserIdentity {
  user_id: string;
  username: string;
}

export interface AccessToken {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface Conversation {
  conversation_id: string;
  member_ids: string[];
  created_at: string;
  created: boolean;
}

export interface HistoryMessage {
  server_message_id: string;
  client_message_id: string;
  conversation_id: string;
  sender_id: string;
  recipient_id: string;
  content: string;
  created_at: string;
}

export interface HistoryPage {
  messages: HistoryMessage[];
  next_cursor: string | null;
  has_more: boolean;
}

export type MessageStatus = "sending" | "accepted" | "failed" | "received";

export interface ChatMessage {
  serverMessageId: string | null;
  clientMessageId: string;
  conversationId: string;
  senderId: string;
  recipientId: string;
  content: string;
  sentAt: string;
  status: MessageStatus;
  pushStatus?: string;
}

export interface SocketStatusEvent {
  state: "connected" | "disconnected";
  code: number | null;
  reason: string | null;
}

export interface MessageEvent {
  type: "message";
  server_message_id: string;
  client_message_id: string;
  conversation_id: string;
  sender_id: string;
  recipient_id: string;
  content: string;
  sent_at: string;
}

export interface AcceptedEvent {
  type: "accepted";
  client_message_id: string;
  server_message_id: string;
  conversation_id: string;
  push_status: string;
}

export interface ErrorEvent {
  type: "error";
  code: string;
  message: string;
  client_message_id?: string | null;
}

export interface SyncResultEvent {
  type: "sync_result";
  conversation_id: string;
  messages: MessageEvent[];
  has_more: boolean;
}

export interface PositionAckEvent {
  type: "position_ack";
  conversation_id: string;
  position_type: "delivered" | "read";
  message_id: string | null;
  advanced: boolean;
}

export type ServerEvent =
  | MessageEvent
  | AcceptedEvent
  | ErrorEvent
  | SyncResultEvent
  | PositionAckEvent;

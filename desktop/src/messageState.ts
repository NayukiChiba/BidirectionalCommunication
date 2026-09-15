import type { ChatMessage, HistoryMessage, MessageEvent } from "./types";

export function fromHistoryMessage(message: HistoryMessage): ChatMessage {
  return {
    serverMessageId: message.server_message_id,
    clientMessageId: message.client_message_id,
    conversationId: message.conversation_id,
    senderId: message.sender_id,
    recipientId: message.recipient_id,
    content: message.content,
    sentAt: message.created_at,
    status: "received",
  };
}

export function fromMessageEvent(message: MessageEvent): ChatMessage {
  return {
    serverMessageId: message.server_message_id,
    clientMessageId: message.client_message_id,
    conversationId: message.conversation_id,
    senderId: message.sender_id,
    recipientId: message.recipient_id,
    content: message.content,
    sentAt: message.sent_at,
    status: "received",
  };
}

export function mergeMessages(
  existingMessages: ChatMessage[],
  incomingMessages: ChatMessage[],
): ChatMessage[] {
  const byClientId = new Map<string, ChatMessage>();
  const serverIds = new Set<string>();

  for (const message of [...existingMessages, ...incomingMessages]) {
    const previous = byClientId.get(message.clientMessageId);
    if (message.serverMessageId && serverIds.has(message.serverMessageId) && !previous) {
      continue;
    }
    const merged = previous ? { ...previous, ...message } : message;
    byClientId.set(message.clientMessageId, merged);
    if (merged.serverMessageId) {
      serverIds.add(merged.serverMessageId);
    }
  }

  return [...byClientId.values()].sort((left, right) => {
    const timeDifference = Date.parse(left.sentAt) - Date.parse(right.sentAt);
    return timeDifference || left.clientMessageId.localeCompare(right.clientMessageId);
  });
}

export function getLastServerMessageId(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const serverMessageId = messages[index]?.serverMessageId;
    if (serverMessageId) {
      return serverMessageId;
    }
  }
  return null;
}

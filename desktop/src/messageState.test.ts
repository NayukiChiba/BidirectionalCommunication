import { describe, expect, it } from "vitest";

import { getLastServerMessageId, mergeMessages } from "./messageState";
import type { ChatMessage } from "./types";

function createMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    serverMessageId: null,
    clientMessageId: "client-1",
    conversationId: "conversation-1",
    senderId: "user-1",
    recipientId: "user-2",
    content: "测试消息",
    sentAt: "2026-09-15T10:00:00Z",
    status: "sending",
    ...overrides,
  };
}

describe("mergeMessages", () => {
  it("用服务端确认更新乐观消息", () => {
    const optimistic = createMessage();
    const confirmed = createMessage({
      serverMessageId: "server-1",
      status: "accepted",
    });

    const result = mergeMessages([optimistic], [confirmed]);

    expect(result).toHaveLength(1);
    expect(result[0]?.serverMessageId).toBe("server-1");
    expect(result[0]?.status).toBe("accepted");
  });

  it("按服务端消息标识忽略重复实时事件", () => {
    const first = createMessage({ serverMessageId: "server-1" });
    const duplicate = createMessage({
      serverMessageId: "server-1",
      clientMessageId: "unexpected-duplicate",
    });

    expect(mergeMessages([first], [duplicate])).toHaveLength(1);
  });
});

describe("getLastServerMessageId", () => {
  it("跳过尚未确认的尾部消息", () => {
    const messages = [
      createMessage({ serverMessageId: "server-1" }),
      createMessage({ clientMessageId: "client-2" }),
    ];

    expect(getLastServerMessageId(messages)).toBe("server-1");
  });
});

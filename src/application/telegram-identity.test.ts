import { describe, expect, it } from "vitest";
import { commandActor, toolActor } from "./telegram-identity.js";

describe("Telegram identity", () => {
  it("overrides model-provided user IDs and display names with the authenticated sender", () => {
    expect(toolActor({ messageChannel: "telegram", requesterSenderId: "42" })).toEqual({ telegramId: "42" });
  });
  it("refuses unbound Telegram journal calls", () => {
    expect(() => toolActor({ messageChannel: "telegram" })).toThrow();
    expect(() => toolActor({ messageChannel: "web", requesterSenderId: "42" })).toThrow();
    expect(() => commandActor({ channel: "telegram", senderId: "42", isAuthorizedSender: false })).toThrow();
  });
});

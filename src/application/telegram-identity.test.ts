import { describe, expect, it } from "vitest";
import { bindTelegramUser } from "./telegram-identity.js";

describe("Telegram identity", () => {
  it("overrides model-provided user IDs and display names with the authenticated sender", () => {
    expect(bindTelegramUser({ user: { id: "wrong", name: "Anton Govorov" }, scope: "month" },
      { messageChannel: "telegram", requesterSenderId: "42" })).toEqual({
      user: { externalRefs: [{ system: "telegram", id: "42" }] }, scope: "month",
    });
  });
  it("refuses unbound Telegram journal calls", () => {
    expect(() => bindTelegramUser({ user: { name: "Anton" } }, { messageChannel: "telegram" })).toThrow();
  });
});

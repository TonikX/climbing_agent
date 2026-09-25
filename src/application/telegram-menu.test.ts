import { afterEach, describe, expect, it, vi } from "vitest";
import { registerTelegramMenu } from "./telegram-menu.js";

describe("Telegram journal menu", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("registers a journal command with direct action buttons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ active: true, status: "active", summary: {} }),
    }));
    process.env.CLIMBING_API_URL = "http://api";
    process.env.CLIMBING_API_KEY = "test-key";
    const commands: Array<Record<string, unknown>> = [];
    registerTelegramMenu({ registerCommand: (command: unknown) => commands.push(command as Record<string, unknown>) } as never);

    expect(commands.map((command) => command.name)).toEqual([
      "journal", "start_training", "another_attempt", "current_training", "week_stats", "finish_training",
    ]);
    const journal = commands[0];
    const result = await (journal.handler as (ctx: unknown) => Promise<Record<string, unknown>>)({ senderId: "42" });
    expect(result.text).toBe("Тренировка активна. Что сделать?");
    expect(result.interactive).toMatchObject({
      blocks: [{
        type: "buttons",
        buttons: [
          { action: { type: "command", command: "/another_attempt" } },
          { action: { type: "command", command: "/current_training" } },
          { action: { type: "command", command: "/week_stats" } },
          { action: { type: "command", command: "/finish_training" } },
        ],
      }],
    });
  });
});

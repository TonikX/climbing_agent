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
      "journal", "start_training", "toggle_test_mode", "another_attempt",
      "stats_menu", "current_training", "current_training_details", "last_training",
      "week_stats", "month_stats", "progress_stats", "grade_stats", "location_stats",
      "project_stats", "record_stats", "finish_training",
    ]);
    const journal = commands[0];
    const result = await (journal.handler as (ctx: unknown) => Promise<Record<string, unknown>>)({ senderId: "42" });
    expect(result.text).toBe("Тренировка активна. Что сделать?");
    expect(result.interactive).toMatchObject({
      blocks: [{
        type: "buttons",
        buttons: [
          { action: { type: "command", command: "/another_attempt" } },
          { action: { type: "command", command: "/stats_menu" } },
          { action: { type: "command", command: "/finish_training" } },
          { action: { type: "command", command: "/toggle_test_mode" } },
        ],
      }],
    });

    const stats = commands.find((command) => command.name === "stats_menu")!;
    const statsResult = await (stats.handler as () => Promise<Record<string, unknown>>)();
    expect(statsResult.text).toBe("📊 Статистика");
    expect(JSON.stringify(statsResult.interactive)).toContain("/record_stats");
  });
});

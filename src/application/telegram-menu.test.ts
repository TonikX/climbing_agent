import { afterEach, describe, expect, it, vi } from "vitest";
import { registerTelegramMenu } from "./telegram-menu.js";

describe("Telegram journal menu", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows reaching the top without presenting it as a clean ascent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      active: true, routes: [{ route: { name: "Test route" }, attempts: [
        { number: 1, reachedTop: true, cleanAscent: false, falls: 2, style: "unknown", belay: "top_rope" },
      ] }],
    }) }));
    process.env.CLIMBING_API_URL = "http://api";
    process.env.CLIMBING_API_KEY = "test-key";
    const commands: Array<Record<string, unknown>> = [];
    registerTelegramMenu({ registerCommand: (command: unknown) => commands.push(command as Record<string, unknown>) } as never);
    const command = commands.find(command => command.name === "completed_routes")!;
    const result = await (command.handler as (ctx: unknown) => Promise<{text: string}>)({ senderId: "42" });
    expect(result.text).toContain("Test route");
    expect(result.text).toContain("• Долез до конца: да");
    expect(result.text).toContain("• Пролез чисто: нет");
    expect(result.text).toContain("• Стиль: не указан");
    expect(result.text).toContain("• Страховка: верхняя");
    expect(result.text).not.toContain("✅");
  });

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
      "completed_routes", "journal", "start_training", "toggle_test_mode", "another_attempt",
      "stats_menu", "current_training", "current_training_details", "last_training",
      "last_training_details", "week_stats", "month_stats", "progress_stats", "grade_stats", "location_stats",
      "project_stats", "record_stats", "finish_training",
    ]);
    const journal = commands.find(command => command.name === "journal")!;
    const result = await (journal.handler as (ctx: unknown) => Promise<Record<string, unknown>>)({ senderId: "42" });
    expect(result.text).toBe("Тренировка активна. Что сделать?");
    expect(result.interactive).toMatchObject({
      blocks: [{
        type: "buttons",
        buttons: [
          { action: { type: "command", command: "/another_attempt" } },
          { action: { type: "command", command: "/completed_routes" } },
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

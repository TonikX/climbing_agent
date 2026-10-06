import { afterEach, describe, expect, it, vi } from "vitest";
import { formatStatisticsResult, registerTelegramMenu } from "./telegram-menu.js";
import { clearTelegramSessions } from "../storage/api-client.js";

describe("statistics formatting", () => {
  const previous = { dateFrom: "2026-08-01", period: "2026-08", trainingsCount: 6,
    completedRoutes: 13, routesCount: 24, completionRate: 0.54,
    attemptsPerCompletedRoute: 4.2, maxCompletedGrade: "6B+" };
  const current = { dateFrom: "2026-09-01", period: "2026-09", trainingsCount: 8,
    durationMinutes: 1180, completedRoutes: 18, routesCount: 31, attemptsCount: 67,
    completionRate: 0.58, attemptsPerRoute: 2.16, attemptsPerCompletedRoute: 3.7,
    maxAttemptedGrade: "7A", maxReachedTopGrade: "6C+", maxCompletedGrade: "6C",
    comparison: { trainingsCount: "up", completedRoutes: "up", completionRate: "up",
      attemptsPerCompletedRoute: "down", maxCompletedGrade: "up" } };

  it("shows month maxima, efficiency, bars and previous month", () => {
    const output = formatStatisticsResult("month", { ...current, previousPeriod: previous,
      grades: [{ grade: "6C", completionRate: 0.375, completedRoutes: 3, routesCount: 8 }] });
    for (const expected of ["Сентябрь 2026", "19 ч 40 мин", "58%", "2.2", "█", "░", "3/8",
      "пробовал: 7A", "дошёл до конца: 6C+", "чисто: 6C", "Август 2026",
      "↑ максимум чистого пролаза: 6B+ → 6C", "↓ попыток на чистый пролаз: 4.2 → 3.7"])
      expect(output).toContain(expected);
  });

  it("emphasizes completed route ratio rather than attempt ratio", () => {
    const output = formatStatisticsResult("grades", { grades: [{ grade: "6C", completionRate: 0.375,
      completedRoutes: 3, routesCount: 8, attemptsCount: 19 }] });
    expect(output).toContain("38%");
    expect(output).toContain("3/8");
    expect(output).toContain("19 попыток");
    expect(output).not.toContain("3/19");
  });

  it("renders chronological trends with backend arrows", () => {
    const output = formatStatisticsResult("progress", { periods: [current, previous] });
    expect(output.indexOf("Авг")).toBeLessThan(output.indexOf("Сен"));
    for (const expected of ["Максимальная чистая категория:", "Чистые пролазы:", "Закрыто трасс:",
      "Тренировки:", "█", "6C ↑", "58% ↑", "Последние месяцы:", "4.2 → 3.7"])
      expect(output).toContain(expected);
    expect(output).not.toContain("7A");
  });

  it("handles empty periods and missing grades without arrows", () => {
    expect(formatStatisticsResult("progress", { periods: [] })).toContain("Данных пока нет");
    const output = formatStatisticsResult("progress", { periods: [
      { ...current, maxCompletedGrade: null, comparison: { maxCompletedGrade: null } }, previous] });
    expect(output).toContain("максимум чистого пролаза: 6B+ → —");
    expect(output).not.toContain("↑ максимум чистого пролаза");
  });
});

describe("Telegram journal menu", () => {
  afterEach(() => { vi.unstubAllGlobals(); clearTelegramSessions(); });

  it("updates the sender's profile directly without an LLM and reports auth failures", async () => {
    process.env.CLIMBING_API_URL = "http://api";
    process.env.CLIMBING_API_KEY = "test-key";
    const fetchMock = vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({access_token:"profile-token",expires_in:900})})
      .mockResolvedValueOnce({ok:true,json:async()=>({name:"Антон",timezone:"Europe/Moscow"})});
    vi.stubGlobal("fetch",fetchMock);
    const commands: Array<Record<string,unknown>> = [];
    registerTelegramMenu({registerCommand:(command:unknown)=>commands.push(command as Record<string,unknown>)} as never);
    const handler = commands.find(c=>c.name === "profile_name")!.handler as (ctx:unknown)=>Promise<{text:string}>;
    const result = await handler({channel:"telegram",senderId:"43",isAuthorizedSender:true,args:"Антон"});
    expect(result.text).toContain("Имя: Антон");
    expect(fetchMock.mock.calls[0][1].body).toBe(JSON.stringify({telegram_id:"43"}));
    expect(fetchMock.mock.calls[1][0]).toBe("http://api/api/v1/me");
    expect(fetchMock.mock.calls[1][1].method).toBe("PATCH");
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({name:"Антон"}));
    clearTelegramSessions();
    fetchMock.mockResolvedValue({ok:false,status:403});
    const menu = commands.find(c=>c.name === "journal")!.handler as (ctx:unknown)=>Promise<{text:string}>;
    const failed = await menu({channel:"telegram",senderId:"43",isAuthorizedSender:true});
    expect(failed.text).toContain("Не удалось");
    expect(failed.text).not.toContain("Сейчас активной тренировки нет");
  });

  it("shows reaching the top without presenting it as a clean ascent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({access_token:"token",expires_in:900})}).mockResolvedValue({ ok: true, json: async () => ({
      active: true, routes: [{ route: { name: "Test route" }, attempts: [
        { number: 1, reachedTop: true, cleanAscent: false, falls: 2, style: "unknown", belay: "top_rope" },
      ] }],
    }) }));
    process.env.CLIMBING_API_URL = "http://api";
    process.env.CLIMBING_API_KEY = "test-key";
    const commands: Array<Record<string, unknown>> = [];
    registerTelegramMenu({ registerCommand: (command: unknown) => commands.push(command as Record<string, unknown>) } as never);
    const command = commands.find(command => command.name === "completed_routes")!;
    const result = await (command.handler as (ctx: unknown) => Promise<{text: string}>)({ senderId: "42", channel: "telegram", isAuthorizedSender: true });
    expect(result.text).toContain("Test route");
    expect(result.text).toContain("• Долез до конца: да");
    expect(result.text).toContain("• Пролез чисто: нет");
    expect(result.text).toContain("• Стиль: не указан");
    expect(result.text).toContain("• Страховка: верхняя");
    expect(result.text).not.toContain("✅");
  });

  it("registers a journal command with direct action buttons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({access_token:"token",expires_in:900})}).mockResolvedValue({
      ok: true,
      json: async () => ({ active: true, status: "active", summary: {} }),
    }));
    process.env.CLIMBING_API_URL = "http://api";
    process.env.CLIMBING_API_KEY = "test-key";
    const commands: Array<Record<string, unknown>> = [];
    registerTelegramMenu({ registerCommand: (command: unknown) => commands.push(command as Record<string, unknown>) } as never);

    expect(commands.map((command) => command.name)).toEqual([
      "profile", "profile_name", "timezone",
      "completed_routes", "journal", "start_training", "toggle_test_mode", "another_attempt",
      "stats_menu", "current_training", "current_training_details", "last_training",
      "last_training_details", "week_stats", "month_stats", "progress_stats", "grade_stats", "location_stats",
      "project_stats", "record_stats", "finish_training",
    ]);
    const journal = commands.find(command => command.name === "journal")!;
    const result = await (journal.handler as (ctx: unknown) => Promise<Record<string, unknown>>)({ senderId: "42", channel:"telegram", isAuthorizedSender:true });
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
          { action: { type: "command", command: "/profile" } },
        ],
      }],
    });

    const stats = commands.find((command) => command.name === "stats_menu")!;
    const statsResult = await (stats.handler as () => Promise<Record<string, unknown>>)();
    expect(statsResult.text).toBe("📊 Статистика");
    expect(JSON.stringify(statsResult.interactive)).toContain("/record_stats");
  });
});

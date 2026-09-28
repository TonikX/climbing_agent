import type {
  OpenClawPluginApi,
  PluginCommandContext,
  PluginCommandResult,
} from "openclaw/plugin-sdk/plugin-entry";
import { createJournalTools } from "./journal.js";
import { usePostgresApi } from "../storage/api-client.js";

const journal = createJournalTools();
const startTraining = usePostgresApi(journal.start_climbing_training);
const currentTraining = usePostgresApi(journal.get_current_climbing_training);
const statistics = usePostgresApi(journal.get_climbing_statistics);
const finishTraining = usePostgresApi(journal.finish_climbing_training);
const setTestMode = usePostgresApi(journal.set_climbing_test_mode);

type JsonRecord = Record<string, unknown>;

type JournalState = { active: boolean; testMode: boolean };

function menuButtons(active: boolean, testMode: boolean) {
  const buttons = active ? [
    { label: "🎙 Ещё попытка", action: { type: "command" as const, command: "/another_attempt" } },
    { label: "🏁 Трассы до конца", action: { type: "command" as const, command: "/completed_routes" } },
    { label: "📊 Статистика", action: { type: "command" as const, command: "/stats_menu" } },
    { label: "✅ Завершить тренировку", action: { type: "command" as const, command: "/finish_training" } },
  ] : [
    { label: "▶️ Начать тренировку", action: { type: "command" as const, command: "/start_training" } },
    { label: "📊 Статистика", action: { type: "command" as const, command: "/stats_menu" } },
  ];
  buttons.push({
    label: testMode ? "🧪 Тестовый режим: ВКЛ" : "🧪 Тестовый режим: выкл",
    action: { type: "command" as const, command: "/toggle_test_mode" },
  });
  return { blocks: [{ type: "buttons" as const, buttons }] };
}

function telegramUser(ctx: PluginCommandContext) {
  const id = ctx.senderId?.trim();
  if (!id) throw new Error("Telegram не передал идентификатор пользователя");
  return { externalRefs: [{ system: "telegram", id }] };
}

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" ? value as JsonRecord : {};
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function array(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function duration(value: unknown): string {
  const minutes = number(value);
  if (!minutes) return "длительность не указана";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours ? `${hours} ч${rest ? ` ${rest} мин` : ""}` : `${rest} мин`;
}

function statisticsButtons() {
  return { blocks: [{ type: "buttons" as const, buttons: [
    { label: "🧗 Текущая тренировка", action: { type: "command" as const, command: "/current_training" } },
    { label: "🕘 Последняя тренировка", action: { type: "command" as const, command: "/last_training" } },
    { label: "📅 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
    { label: "🗓 Этот месяц", action: { type: "command" as const, command: "/month_stats" } },
    { label: "📈 Прогресс", action: { type: "command" as const, command: "/progress_stats" } },
    { label: "🎯 По категориям", action: { type: "command" as const, command: "/grade_stats" } },
    { label: "📍 По локациям", action: { type: "command" as const, command: "/location_stats" } },
    { label: "🔄 Проекты", action: { type: "command" as const, command: "/project_stats" } },
    { label: "🏆 Рекорды", action: { type: "command" as const, command: "/record_stats" } },
    { label: "← Главное меню", action: { type: "command" as const, command: "/journal" } },
  ] }] };
}

function statisticsMenu(textValue = "📊 Статистика"): PluginCommandResult {
  return { text: textValue, interactive: statisticsButtons() };
}

function statisticsBack(textValue: string, extra: Array<{label: string; command: string}> = []): PluginCommandResult {
  return { text: textValue, interactive: { blocks: [{ type: "buttons", buttons: [
    ...extra.map((item) => ({ label: item.label, action: { type: "command" as const, command: item.command } })),
    { label: "← Статистика", action: { type: "command" as const, command: "/stats_menu" } },
  ] }] } };
}

function summaryLines(title: string, value: JsonRecord, subtitle?: string): string {
  return [
    title,
    subtitle,
    "",
    `${number(value.routesCount)} трасс · ${number(value.attemptsCount)} попыток`,
    "",
    `🏁 ${number(value.reachedTopRoutes)} — долез до конца`,
    `✅ ${number(value.completedRoutes)} — пролез чисто`,
    `❓ ${number(value.unknownCleanRoutes)} — чистота не уточнена`,
    `👁 ${number(value.onsightCount)} Onsight`,
    `⚡ ${number(value.flashCount)} Flash`,
    `🎯 ${number(value.redpointCount)} Red Point`,
    `❔ ${number(value.unknownStyleCount)} — стиль не указан`,
    `🔄 ${number(value.activeProjects)} проекта`,
    "",
    `Максимальная категория: ${text(value.maxGrade)}`,
  ].filter((line) => line !== undefined).join("\n");
}

function routeDetailLines(title: string, routes: unknown): string {
  const lines = [title];
  for (const group of array(routes)) {
    const route = record(group.route);
    const section = record(group.section);
    lines.push("", `${text(section.name, "Без сектора")} · ${text(route.name, "Без названия")} ${text(route.grade, "")}`.trim());
    for (const attempt of array(group.attempts)) {
      const mark = attempt.cleanAscent === true ? "✅" : attempt.reachedTop === true ? "🏁" : "🔄";
      const fact = (value: unknown) => value === true ? "да" : value === false ? "нет" : "не уточнено";
      const outcome = `долез: ${fact(attempt.reachedTop)} · чисто: ${fact(attempt.cleanAscent)}`;
      const details = [attempt.highPoint !== null && attempt.highPoint !== undefined ? `до ${number(attempt.highPoint)}` : "",
        attempt.falls !== null && attempt.falls !== undefined ? `${number(attempt.falls)} срыв.` : ""].filter(Boolean).join(", ");
      lines.push(`${mark} №${number(attempt.number)} · ${outcome}${details ? ` — ${details}` : ""}`);
    }
  }
  if (lines.length === 1) lines.push("", "Попыток пока нет.");
  return lines.join("\n");
}

export function formatStatisticsResult(scope: string, raw: unknown): string {
  const result = record(raw);
  if (scope === "last_training") {
    const training = record(result.training);
    if (!result.training) return "Завершённых тренировок пока нет.";
    const location = record(training.location);
    return summaryLines("🧗 Последняя тренировка", training,
      `${text(training.date)} · ${text(location.name, "Локация не указана")} · ${duration(training.durationMinutes)}`);
  }
  if (scope === "progress") {
    const lines = ["📈 Прогресс за последние месяцы"];
    for (const period of array(result.periods)) lines.push("", `${text(period.period)}: ${number(period.trainingsCount)} трен. · ${number(period.reachedTopRoutes)} до конца · ${number(period.completedRoutes)} чисто · max ${text(period.maxGrade)}`);
    if (lines.length === 1) lines.push("", "Данных пока нет.");
    return lines.join("\n");
  }
  if (scope === "grades") {
    const lines = ["🎯 Статистика по категориям"];
    for (const grade of array(result.grades)) lines.push(`${text(grade.grade)} — ${number(grade.routesCount)} трасс · ${number(grade.attemptsCount)} попыток · 🏁 ${number(grade.reachedTopRoutes)} до конца · ✅ ${number(grade.completedRoutes)} чисто`);
    if (lines.length === 1) lines.push("", "Данных пока нет.");
    return lines.join("\n");
  }
  if (scope === "locations") {
    const lines = ["📍 Статистика по локациям"];
    for (const item of array(result.locations)) {
      const location = record(item.location);
      lines.push(`${text(location.name, "Без локации")} — ${number(item.trainingsCount)} трен. · ${number(item.routesCount)} трасс · 🏁 ${number(item.reachedTopRoutes)} до конца · ✅ ${number(item.completedRoutes)} чисто`);
    }
    if (lines.length === 1) lines.push("", "Данных пока нет.");
    return lines.join("\n");
  }
  if (scope === "projects") {
    const lines = ["🔄 Активные проекты"];
    for (const item of array(result.projects)) {
      const route = record(item.route);
      const progress = item.highPoint !== null && item.highPoint !== undefined ? ` · до ${number(item.highPoint)}/${text(item.totalMoves)}` : "";
      lines.push(`${text(route.name, "Без названия")} ${text(route.grade, "")}${progress}`.trim());
    }
    if (lines.length === 1) lines.push("", "Активных проектов нет.");
    return lines.join("\n");
  }
  if (scope === "records") {
    const records = record(result.records);
    return ["🏆 Рекорды", "", `Высшая категория чистого пролаза: ${text(records.highestCompletedGrade)}`,
      `Высший Flash: ${text(records.highestFlashGrade)}`, `Высший Red Point: ${text(records.highestRedpointGrade)}`, "",
      `Тренировок: ${number(records.totalTrainings)}`, `Попыток: ${number(records.totalAttempts)}`,
      `Чисто пройдено трасс: ${number(records.totalCompletedRoutes)}`].join("\n");
  }
  const titles: Record<string, string> = {
    week: "📅 Эта неделя", month: "🗓 Этот месяц", grade: `🎯 Категория ${text(result.grade, "")}`,
    route: "🧗 Статистика по трассе", custom: "📊 Статистика за период",
  };
  return summaryLines(titles[scope] ?? "📊 Статистика", result, `${number(result.trainingsCount)} тренировок`);
}

function menu(textValue: string, state: JournalState): PluginCommandResult {
  const mode = state.testMode ? "\n\n🧪 Тестовый режим включён: новые пролазы не попадут в статистику." : "";
  return { text: `${textValue}${mode}`, interactive: menuButtons(state.active, state.testMode) };
}

function errorReply(error: unknown, state: JournalState): PluginCommandResult {
  const message = error instanceof Error ? error.message : String(error);
  return menu(`Не удалось выполнить действие: ${message}`, state);
}

async function journalState(ctx: PluginCommandContext): Promise<JournalState> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "summary" }));
    return {
      active: result.active !== false && result.status !== "not_found",
      testMode: result.testMode === true,
    };
  } catch {
    return { active: false, testMode: false };
  }
}

async function openMenu(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  const state = await journalState(ctx);
  return menu(state.active ? "Тренировка активна. Что сделать?" : "Сейчас активной тренировки нет.", state);
}

async function start(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const state = await journalState(ctx);
    if (state.active) return menu("Тренировка уже активна.", state);
    await startTraining.execute({ user: telegramUser(ctx) });
    return menu("Тренировка начата ▶️ Можешь отправлять пролазы голосом или текстом.", { ...state, active: true });
  } catch (error) {
    return errorReply(error, await journalState(ctx));
  }
}

async function toggleTestMode(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  const state = await journalState(ctx);
  try {
    const enabled = !state.testMode;
    await setTestMode.execute({ user: telegramUser(ctx), enabled });
    return menu(enabled ? "Тестовый режим включён." : "Тестовый режим выключен.", { ...state, testMode: enabled });
  } catch (error) {
    return errorReply(error, state);
  }
}

async function showCurrent(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "summary" }));
    const state = { active: result.active !== false && result.status !== "not_found", testMode: result.testMode === true };
    if (!state.active) return statisticsBack("Сейчас активной тренировки нет.");
    const summary = record(result.summary);
    const location = record(result.location);
    return statisticsBack(summaryLines(
      "📊 Текущая тренировка",
      summary,
      `${text(location.name, "Локация не указана")} · ${duration(result.durationMinutes)}`,
    ), [
      { label: "📋 Все попытки", command: "/current_training_details" },
      { label: "🏁 Трассы до конца", command: "/completed_routes" },
      { label: "🔄 Проекты", command: "/project_stats" },
    ]);
  } catch (error) {
    return statisticsBack(`Не удалось загрузить текущую тренировку: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showCurrentDetails(ctx: PluginCommandContext, completedOnly = false): Promise<PluginCommandResult> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "full" }));
    if (result.active === false) return statisticsBack("Сейчас активной тренировки нет.");
    const routes = completedOnly ? array(result.routes).filter(group =>
      array(group.attempts).some(attempt => attempt.reachedTop === true)) : result.routes;
    return statisticsBack(completedOnly && array(routes).length === 0 ? "Пока нет трасс, на которых подтверждено достижение конца." :
      routeDetailLines(completedOnly ? "🏁 Трассы до конца текущей тренировки" : "📋 Все попытки текущей тренировки", routes),
      [{ label: "← Текущая тренировка", command: "/current_training" }]);
  } catch (error) {
    return statisticsBack(`Не удалось загрузить попытки: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showPeriod(ctx: PluginCommandContext, scope: "week" | "month"): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope }));
    return statisticsBack(formatStatisticsResult(scope, result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить статистику: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLastTraining(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const response = record(await statistics.execute({ user: telegramUser(ctx), scope: "last_training" }));
    if (!response.training) return statisticsBack("Завершённых тренировок пока нет.");
    return statisticsBack(formatStatisticsResult("last_training", response),
      [{ label: "📋 Подробнее", command: "/last_training_details" }]);
  } catch (error) {
    return statisticsBack(`Не удалось загрузить последнюю тренировку: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLastTrainingDetails(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const response = record(await statistics.execute({ user: telegramUser(ctx), scope: "last_training", detail: "full" }));
    const training = record(response.training);
    if (!response.training) return statisticsBack("Завершённых тренировок пока нет.");
    return statisticsBack(routeDetailLines("📋 Последняя тренировка — все попытки", training.routes),
      [{ label: "← Последняя тренировка", command: "/last_training" }]);
  } catch (error) {
    return statisticsBack(`Не удалось загрузить попытки: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showProgress(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope: "progress" }));
    return statisticsBack(formatStatisticsResult("progress", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить прогресс: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showGrades(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope: "grades" }));
    return statisticsBack(formatStatisticsResult("grades", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить категории: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLocations(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope: "locations" }));
    return statisticsBack(formatStatisticsResult("locations", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить локации: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showProjects(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope: "projects", limit: 20 }));
    return statisticsBack(formatStatisticsResult("projects", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить проекты: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showRecords(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics.execute({ user: telegramUser(ctx), scope: "records" }));
    return statisticsBack(formatStatisticsResult("records", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить рекорды: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function finish(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    await finishTraining.execute({ user: telegramUser(ctx) });
    const state = await journalState(ctx);
    return menu("Тренировка завершена ✅", { ...state, active: false });
  } catch (error) {
    return errorReply(error, await journalState(ctx));
  }
}

export function registerTelegramMenu(api: OpenClawPluginApi): void {
  api.registerCommand({
    name: "completed_routes",
    description: "Трассы, на которых долез до конца",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: (ctx) => showCurrentDetails(ctx, true),
  });
  api.registerCommand({
    name: "journal",
    description: "Открыть меню скалолазного журнала",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: openMenu,
  });
  api.registerCommand({
    name: "start_training",
    description: "Начать тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: start,
  });
  api.registerCommand({
    name: "toggle_test_mode",
    description: "Включить или выключить тестовый режим",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: toggleTestMode,
  });
  api.registerCommand({
    name: "another_attempt",
    description: "Записать ещё одну попытку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: async (ctx) => {
      const state = await journalState(ctx);
      if (!state.active) return menu("Сначала начни тренировку.", state);
      return menu("Пришли голосом или текстом результат следующей попытки.", state);
    },
  });
  api.registerCommand({
    name: "stats_menu",
    description: "Открыть статистику",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: async () => statisticsMenu(),
  });
  api.registerCommand({
    name: "current_training",
    description: "Показать текущую тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showCurrent,
  });
  api.registerCommand({
    name: "current_training_details",
    description: "Показать все попытки текущей тренировки",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showCurrentDetails,
  });
  api.registerCommand({
    name: "last_training",
    description: "Показать последнюю тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showLastTraining,
  });
  api.registerCommand({
    name: "last_training_details",
    description: "Показать все попытки последней тренировки",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showLastTrainingDetails,
  });
  api.registerCommand({
    name: "week_stats",
    description: "Показать статистику за неделю",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: (ctx) => showPeriod(ctx, "week"),
  });
  api.registerCommand({
    name: "month_stats",
    description: "Показать статистику за месяц",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: (ctx) => showPeriod(ctx, "month"),
  });
  api.registerCommand({
    name: "progress_stats",
    description: "Показать прогресс",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showProgress,
  });
  api.registerCommand({
    name: "grade_stats",
    description: "Показать статистику по категориям",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showGrades,
  });
  api.registerCommand({
    name: "location_stats",
    description: "Показать статистику по локациям",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showLocations,
  });
  api.registerCommand({
    name: "project_stats",
    description: "Показать активные проекты",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showProjects,
  });
  api.registerCommand({
    name: "record_stats",
    description: "Показать рекорды",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showRecords,
  });
  api.registerCommand({
    name: "finish_training",
    description: "Завершить текущую тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: finish,
  });
}

import type {
  OpenClawPluginApi,
  PluginCommandContext,
  PluginCommandResult,
} from "openclaw/plugin-sdk/plugin-entry";
import { createJournalTools } from "./journal.js";
import { userApi, usePostgresApi } from "../storage/api-client.js";

import { commandActor } from "./telegram-identity.js";

const journal = createJournalTools();
const startTraining = (ctx: PluginCommandContext) => usePostgresApi(journal.start_climbing_training, commandActor(ctx));
const currentTraining = (ctx: PluginCommandContext) => usePostgresApi(journal.get_current_climbing_training, commandActor(ctx));
const statistics = (ctx: PluginCommandContext) => usePostgresApi(journal.get_climbing_statistics, commandActor(ctx));
const finishTraining = (ctx: PluginCommandContext) => usePostgresApi(journal.finish_climbing_training, commandActor(ctx));
const setTestMode = (ctx: PluginCommandContext) => usePostgresApi(journal.set_climbing_test_mode, commandActor(ctx));

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
  buttons.push({ label: "👤 Мой профиль", action: { type: "command" as const, command: "/profile" } });
  return { blocks: [{ type: "buttons" as const, buttons }] };
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
  const lines = [
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
    "Страховка:",
    `🧗 ${number(value.leadAttemptsCount)} — нижняя`,
    `🪢 ${number(value.topRopeAttemptsCount)} — верхняя`,
    ...(number(value.autoBelayAttemptsCount) ? [`🤖 ${number(value.autoBelayAttemptsCount)} — автоматическая`] : []),
    ...(number(value.boulderingAttemptsCount) ? [`🧱 ${number(value.boulderingAttemptsCount)} — боулдеринг`] : []),
    ...(number(value.unknownBelayAttemptsCount) ? [`❔ ${number(value.unknownBelayAttemptsCount)} — страховка не указана`] : []),
    "",
    ...maximumLines(value),
  ];
  return lines.filter((line) => line !== undefined).join("\n");
}

function styleLabel(value: unknown): string {
  return ({ onsight: "Onsight", flash: "Flash", redpoint: "Red Point", unknown: "не указан" } as Record<string, string>)[String(value)] ?? text(value);
}

function belayLabel(value: unknown): string {
  return ({ lead: "нижняя", top_rope: "верхняя", auto_belay: "автоматическая",
    bouldering: "боулдеринг", unknown: "не указана" } as Record<string, string>)[String(value)] ?? text(value);
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
      lines.push("", `${mark} Попытка №${number(attempt.number)}`,
        `• Долез до конца: ${fact(attempt.reachedTop)}`,
        `• Пролез чисто: ${fact(attempt.cleanAscent)}`,
        `• Стиль: ${styleLabel(attempt.style)}`,
        `• Страховка: ${belayLabel(attempt.belay)}`,
        `• Срывы: ${attempt.falls === null || attempt.falls === undefined ? "не указаны" : number(attempt.falls)}`);
      if (attempt.highPoint !== null && attempt.highPoint !== undefined) lines.push(`• Высшая точка: ${number(attempt.highPoint)}`);
      if (attempt.notes) lines.push(`• Комментарий: ${text(attempt.notes)}`);
    }
  }
  if (lines.length === 1) lines.push("", "Попыток пока нет.");
  return lines.join("\n");
}

function maximumLines(value: JsonRecord): string[] {
  return ["Максимум:", `🧗 пробовал: ${text(value.maxAttemptedGrade ?? value.maxGrade)}`,
    `🏁 дошёл до конца: ${text(value.maxReachedTopGrade)}`, `✅ чисто: ${text(value.maxCompletedGrade)}`];
}

function percent(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function decimal(value: unknown): string {
  return typeof value === "number" ? value.toFixed(1) : "—";
}

function bar(value: number): string {
  const filled = Math.round(Math.max(0, Math.min(1, value)) * 8);
  return "█".repeat(filled) + "░".repeat(8 - filled);
}

function monthLabel(value: unknown, short = false): string {
  const match = /^(\d{4})-(\d{2})/.exec(text(value, ""));
  if (!match || Number(match[2]) < 1 || Number(match[2]) > 12) return "Период";
  const name = new Intl.DateTimeFormat("ru-RU", { month: short ? "short" : "long", timeZone: "UTC" })
    .format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)));
  return `${name[0].toUpperCase()}${name.slice(1)} ${match[1]}`;
}

function arrow(comparison: JsonRecord, key: string): string {
  return ({ up: "↑", down: "↓", equal: "=" } as Record<string, string>)[String(comparison[key])] ?? "";
}

function comparisonLines(current: JsonRecord, previous: JsonRecord): string[] {
  const changes = record(current.comparison);
  const metrics: Array<[string, string, (value: unknown) => string]> = [
    ["trainingsCount", "тренировок", value => String(number(value))],
    ["completedRoutes", "чистых пролазов", value => String(number(value))],
    ["maxCompletedGrade", "максимум чистого пролаза", value => text(value)],
    ["completionRate", "доля закрытых трасс", percent],
    ["attemptsPerCompletedRoute", "попыток на чистый пролаз", decimal],
  ];
  return metrics.map(([key, label, format]) =>
    `${arrow(changes, key)} ${label}: ${format(previous[key])} → ${format(current[key])}`.trim());
}

export function formatStatisticsResult(scope: string, raw: unknown): string {
  const result = record(raw);
  if (scope === "month") {
    const lines = [`🗓 ${monthLabel(result.dateFrom)}`, "",
      `${number(result.trainingsCount)} тренировок · ${duration(result.durationMinutes)}`,
      `${number(result.routesCount)} трасс · ${number(result.attemptsCount)} попыток`, "",
      `🏁 ${number(result.reachedTopRoutes)} — дошёл до конца`,
      `✅ ${number(result.completedRoutes)} — пролез чисто`,
      `❓ ${number(result.unknownCleanRoutes)} — чистота не уточнена`,
      `🔄 ${number(result.activeProjects)} — проекты`, "",
      `👁 ${number(result.onsightCount)} Onsight · ⚡ ${number(result.flashCount)} Flash · 🎯 ${number(result.redpointCount)} Red Point`,
      `❔ ${number(result.unknownStyleCount)} — стиль не указан`,
      `Страховка (попытки): нижняя ${number(result.leadAttemptsCount)} · верхняя ${number(result.topRopeAttemptsCount)}`,
      `Автоматическая ${number(result.autoBelayAttemptsCount)} · боулдеринг ${number(result.boulderingAttemptsCount)} · не указана ${number(result.unknownBelayAttemptsCount)}`,
      "", "Эффективность:", `✅ ${percent(result.completionRate)} трасс закрыто`,
      `🎯 ${decimal(result.attemptsPerRoute)} попытки на трассу`,
      `🏆 ${decimal(result.attemptsPerCompletedRoute)} попытки на чистый пролаз`, "", "Категории:"];
    const grades = array(result.grades);
    for (const grade of grades) lines.push(`${text(grade.grade)} ${bar(number(grade.completionRate))} ${number(grade.completedRoutes)}/${number(grade.routesCount)}`);
    if (!grades.length) lines.push("Данных пока нет.");
    lines.push("", ...maximumLines(result));
    const previous = record(result.previousPeriod);
    if (result.previousPeriod) {
      lines.push("", `По сравнению с ${monthLabel(previous.dateFrom)} (полный месяц):`);
      if (!number(previous.trainingsCount)) lines.push("В предыдущем месяце нет нетестовых данных.");
      else lines.push(...comparisonLines(result, previous));
    }
    return lines.join("\n");
  }
  if (scope === "last_training") {
    const training = record(result.training);
    if (!result.training) return "Завершённых тренировок пока нет.";
    const location = record(training.location);
    return summaryLines("🧗 Последняя тренировка", training,
      `${text(training.date)} · ${text(location.name, "Локация не указана")} · ${duration(training.durationMinutes)}`);
  }
  if (scope === "progress") {
    const periods = array(result.periods).slice().reverse();
    const lines = ["📈 Прогресс"];
    if (!periods.length) return lines.concat("", "Данных пока нет.").join("\n");
    const largest = Math.max(1, ...periods.map(p => number(p.completedRoutes)));
    const trends: Array<[string, string, (p: JsonRecord) => string]> = [
      ["Максимальная чистая категория:", "maxCompletedGrade", p => text(p.maxCompletedGrade)],
      ["Чистые пролазы:", "completedRoutes", p => `${bar(number(p.completedRoutes) / largest)} ${number(p.completedRoutes)}`],
      ["Закрыто трасс:", "completionRate", p => percent(p.completionRate)],
      ["Тренировки:", "trainingsCount", p => String(number(p.trainingsCount))],
    ];
    for (const [title, key, format] of trends) {
      lines.push("", title);
      for (const period of periods) lines.push(`${monthLabel(period.period, true)}  ${format(period)} ${arrow(record(period.comparison), key)}`.trim());
    }
    if (periods.length > 1) lines.push("", "Последние месяцы:",
      ...comparisonLines(periods[periods.length - 1], periods[periods.length - 2]));
    return lines.join("\n");
  }
  if (scope === "grades") {
    const lines = ["🎯 Статистика по категориям"];
    for (const grade of array(result.grades)) lines.push(`${text(grade.grade)}  ✅ ${percent(grade.completionRate)} · ${number(grade.completedRoutes)}/${number(grade.routesCount)} · ${number(grade.attemptsCount)} попыток`);
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

function errorReply(error: unknown): PluginCommandResult {
  const message = error instanceof Error ? error.message : String(error);
  return { text: `Не удалось выполнить действие: ${message}` };
}

async function journalState(ctx: PluginCommandContext): Promise<JournalState> {
    const result = record(await currentTraining(ctx).execute({ detail: "summary" }));
    return {
      active: result.active !== false && result.status !== "not_found",
      testMode: result.testMode === true,
    };
}

async function openMenu(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const state = await journalState(ctx);
    return menu(state.active ? "Тренировка активна. Что сделать?" : "Сейчас активной тренировки нет.", state);
  } catch (error) { return errorReply(error); }
}

async function showProfile(ctx: PluginCommandContext, update?: Record<string, string>): Promise<PluginCommandResult> {
  try {
    const profile = record(await userApi(commandActor(ctx), "/api/v1/me", update ? "PATCH" : "GET", update));
    return { text: `👤 Мой профиль\nИмя: ${text(profile.name)}\nЧасовой пояс: ${text(profile.timezone)}\n\n` +
      "Изменить имя: /profile_name Антон\nИзменить часовой пояс: /timezone Europe/Moscow\nОткрыть журнал: /journal" };
  } catch (error) { return errorReply(error); }
}

async function start(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const state = await journalState(ctx);
    if (state.active) return menu("Тренировка уже активна.", state);
    await startTraining(ctx).execute({  });
    return menu("Тренировка начата ▶️ Можешь отправлять пролазы голосом или текстом.", { ...state, active: true });
  } catch (error) {
    return errorReply(error);
  }
}

async function toggleTestMode(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const state = await journalState(ctx);
    const enabled = !state.testMode;
    await setTestMode(ctx).execute({ enabled });
    return menu(enabled ? "Тестовый режим включён." : "Тестовый режим выключен.", { ...state, testMode: enabled });
  } catch (error) {
    return errorReply(error);
  }
}

async function showCurrent(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await currentTraining(ctx).execute({ detail: "summary" }));
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
    const result = record(await currentTraining(ctx).execute({ detail: "full" }));
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
    const result = record(await statistics(ctx).execute({ scope }));
    return statisticsBack(formatStatisticsResult(scope, result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить статистику: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLastTraining(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const response = record(await statistics(ctx).execute({ scope: "last_training" }));
    if (!response.training) return statisticsBack("Завершённых тренировок пока нет.");
    return statisticsBack(formatStatisticsResult("last_training", response),
      [{ label: "📋 Подробнее", command: "/last_training_details" }]);
  } catch (error) {
    return statisticsBack(`Не удалось загрузить последнюю тренировку: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLastTrainingDetails(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const response = record(await statistics(ctx).execute({ scope: "last_training", detail: "full" }));
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
    const result = record(await statistics(ctx).execute({ scope: "progress" }));
    return statisticsBack(formatStatisticsResult("progress", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить прогресс: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showGrades(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics(ctx).execute({ scope: "grades" }));
    return statisticsBack(formatStatisticsResult("grades", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить категории: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showLocations(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics(ctx).execute({ scope: "locations" }));
    return statisticsBack(formatStatisticsResult("locations", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить локации: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showProjects(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics(ctx).execute({ scope: "projects", limit: 20 }));
    return statisticsBack(formatStatisticsResult("projects", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить проекты: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function showRecords(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await statistics(ctx).execute({ scope: "records" }));
    return statisticsBack(formatStatisticsResult("records", result));
  } catch (error) {
    return statisticsBack(`Не удалось загрузить рекорды: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function finish(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    await finishTraining(ctx).execute({  });
    const state = await journalState(ctx);
    return menu("Тренировка завершена ✅", { ...state, active: false });
  } catch (error) {
    return errorReply(error);
  }
}

export function registerTelegramMenu(api: OpenClawPluginApi): void {
  api.registerCommand({ name: "profile", description: "Мой профиль", channels: ["telegram"],
    acceptsArgs: false, handler: (ctx) => showProfile(ctx) });
  api.registerCommand({ name: "profile_name", description: "Изменить своё имя", channels: ["telegram"],
    acceptsArgs: true, handler: (ctx) => ctx.args?.trim()
      ? showProfile(ctx, { name: ctx.args.trim() }) : Promise.resolve({ text: "Напиши /profile_name и своё имя" }) });
  api.registerCommand({ name: "timezone", description: "Изменить часовой пояс", channels: ["telegram"],
    acceptsArgs: true, handler: (ctx) => ctx.args?.trim()
      ? showProfile(ctx, { timezone: ctx.args.trim() }) : Promise.resolve({ text: "Напиши /timezone Europe/Moscow или свой часовой пояс IANA" }) });
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

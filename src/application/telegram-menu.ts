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
const weekStatistics = usePostgresApi(journal.get_climbing_statistics);
const finishTraining = usePostgresApi(journal.finish_climbing_training);
const setTestMode = usePostgresApi(journal.set_climbing_test_mode);

type JsonRecord = Record<string, unknown>;

type JournalState = { active: boolean; testMode: boolean };

function menuButtons(active: boolean, testMode: boolean) {
  const buttons = active ? [
    { label: "🎙 Ещё попытка", action: { type: "command" as const, command: "/another_attempt" } },
    { label: "📋 Текущая тренировка", action: { type: "command" as const, command: "/current_training" } },
    { label: "📊 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
    { label: "✅ Завершить тренировку", action: { type: "command" as const, command: "/finish_training" } },
  ] : [
    { label: "▶️ Начать тренировку", action: { type: "command" as const, command: "/start_training" } },
    { label: "📊 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
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
    if (!state.active) return menu("Сейчас активной тренировки нет.", state);
    const summary = record(result.summary);
    const location = record(result.location);
    return menu([
      `Текущая тренировка${location.name ? ` · ${text(location.name)}` : ""}`,
      `Трасс: ${number(summary.routesCount)}, попыток: ${number(summary.attemptsCount)}`,
      `Пролезено: ${number(summary.completedRoutes)}, проектов: ${number(summary.activeProjects)}`,
      `Максимальная категория: ${text(summary.maxGrade)}`,
    ].join("\n"), state);
  } catch (error) {
    return errorReply(error, await journalState(ctx));
  }
}

async function showWeek(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await weekStatistics.execute({ user: telegramUser(ctx), scope: "week" }));
    return menu([
      "Статистика за эту неделю",
      `Тренировок: ${number(result.trainingsCount)}`,
      `Трасс: ${number(result.routesCount)}, попыток: ${number(result.attemptsCount)}`,
      `Пролезено: ${number(result.completedRoutes)}, проектов: ${number(result.activeProjects)}`,
      `Максимальная категория: ${text(result.maxGrade)}`,
    ].join("\n"), await journalState(ctx));
  } catch (error) {
    return errorReply(error, await journalState(ctx));
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
    name: "current_training",
    description: "Показать текущую тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showCurrent,
  });
  api.registerCommand({
    name: "week_stats",
    description: "Показать статистику за неделю",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: showWeek,
  });
  api.registerCommand({
    name: "finish_training",
    description: "Завершить текущую тренировку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: finish,
  });
}

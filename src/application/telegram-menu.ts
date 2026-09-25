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

type JsonRecord = Record<string, unknown>;

function menuButtons(active: boolean) {
  const buttons = active ? [
    { label: "🎙 Ещё попытка", action: { type: "command" as const, command: "/another_attempt" } },
    { label: "📋 Текущая тренировка", action: { type: "command" as const, command: "/current_training" } },
    { label: "📊 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
    { label: "✅ Завершить тренировку", action: { type: "command" as const, command: "/finish_training" } },
  ] : [
    { label: "▶️ Начать тренировку", action: { type: "command" as const, command: "/start_training" } },
    { label: "📊 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
  ];
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

function menu(textValue: string, active: boolean): PluginCommandResult {
  return { text: textValue, interactive: menuButtons(active) };
}

function errorReply(error: unknown, active: boolean): PluginCommandResult {
  const message = error instanceof Error ? error.message : String(error);
  return menu(`Не удалось выполнить действие: ${message}`, active);
}

async function activeState(ctx: PluginCommandContext): Promise<boolean> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "summary" }));
    return result.active !== false && result.status !== "not_found";
  } catch {
    return false;
  }
}

async function openMenu(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  const active = await activeState(ctx);
  return menu(active ? "Тренировка активна. Что сделать?" : "Сейчас активной тренировки нет.", active);
}

async function start(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    if (await activeState(ctx)) return menu("Тренировка уже активна.", true);
    await startTraining.execute({ user: telegramUser(ctx) });
    return menu("Тренировка начата ▶️ Можешь отправлять пролазы голосом или текстом.", true);
  } catch (error) {
    return errorReply(error, false);
  }
}

async function showCurrent(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "summary" }));
    if (result.active === false || result.status === "not_found") return menu("Сейчас активной тренировки нет.", false);
    const summary = record(result.summary);
    const location = record(result.location);
    return menu([
      `Текущая тренировка${location.name ? ` · ${text(location.name)}` : ""}`,
      `Трасс: ${number(summary.routesCount)}, попыток: ${number(summary.attemptsCount)}`,
      `Пролезено: ${number(summary.completedRoutes)}, проектов: ${number(summary.activeProjects)}`,
      `Максимальная категория: ${text(summary.maxGrade)}`,
    ].join("\n"), true);
  } catch (error) {
    return errorReply(error, await activeState(ctx));
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
    ].join("\n"), await activeState(ctx));
  } catch (error) {
    return errorReply(error, await activeState(ctx));
  }
}

async function finish(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    await finishTraining.execute({ user: telegramUser(ctx) });
    return menu("Тренировка завершена ✅", false);
  } catch (error) {
    return errorReply(error, await activeState(ctx));
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
    name: "another_attempt",
    description: "Записать ещё одну попытку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: async (ctx) => {
      if (!await activeState(ctx)) return menu("Сначала начни тренировку.", false);
      return menu("Пришли голосом или текстом результат следующей попытки.", true);
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

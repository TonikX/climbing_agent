import type {
  OpenClawPluginApi,
  PluginCommandContext,
  PluginCommandResult,
} from "openclaw/plugin-sdk/plugin-entry";
import { createJournalTools } from "./journal.js";
import { usePostgresApi } from "../storage/api-client.js";

const journal = createJournalTools();
const currentTraining = usePostgresApi(journal.get_current_climbing_training);
const weekStatistics = usePostgresApi(journal.get_climbing_statistics);
const finishTraining = usePostgresApi(journal.finish_climbing_training);

type JsonRecord = Record<string, unknown>;

const menuButtons = {
  blocks: [{
    type: "buttons" as const,
    buttons: [
      { label: "🎙 Ещё попытка", action: { type: "command" as const, command: "/another_attempt" } },
      { label: "📋 Текущая тренировка", action: { type: "command" as const, command: "/current_training" } },
      { label: "📊 Эта неделя", action: { type: "command" as const, command: "/week_stats" } },
      { label: "✅ Завершить тренировку", action: { type: "command" as const, command: "/finish_training" } },
    ],
  }],
};

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

function menu(textValue: string): PluginCommandResult {
  return { text: textValue, interactive: menuButtons };
}

function errorReply(error: unknown): PluginCommandResult {
  const message = error instanceof Error ? error.message : String(error);
  return menu(`Не удалось выполнить действие: ${message}`);
}

async function showCurrent(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    const result = record(await currentTraining.execute({ user: telegramUser(ctx), detail: "summary" }));
    if (result.active === false || result.status === "not_found") return menu("Сейчас активной тренировки нет.");
    const summary = record(result.summary);
    const location = record(result.location);
    return menu([
      `Текущая тренировка${location.name ? ` · ${text(location.name)}` : ""}`,
      `Трасс: ${number(summary.routesCount)}, попыток: ${number(summary.attemptsCount)}`,
      `Пролезено: ${number(summary.completedRoutes)}, проектов: ${number(summary.activeProjects)}`,
      `Максимальная категория: ${text(summary.maxGrade)}`,
    ].join("\n"));
  } catch (error) {
    return errorReply(error);
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
    ].join("\n"));
  } catch (error) {
    return errorReply(error);
  }
}

async function finish(ctx: PluginCommandContext): Promise<PluginCommandResult> {
  try {
    await finishTraining.execute({ user: telegramUser(ctx) });
    return menu("Тренировка завершена ✅");
  } catch (error) {
    return errorReply(error);
  }
}

export function registerTelegramMenu(api: OpenClawPluginApi): void {
  api.registerCommand({
    name: "journal",
    description: "Открыть меню скалолазного журнала",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: async () => menu("Что сделать?"),
  });
  api.registerCommand({
    name: "another_attempt",
    description: "Записать ещё одну попытку",
    channels: ["telegram"],
    acceptsArgs: false,
    handler: async () => menu("Пришли голосом или текстом результат следующей попытки."),
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

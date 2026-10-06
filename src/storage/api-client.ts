import type { TSchema, Static } from "typebox";
import { randomUUID } from "node:crypto";
import type { TelegramActor } from "../application/telegram-identity.js";

type Operation<S extends TSchema> = {
  name: string;
  label: string;
  description: string;
  parameters: S;
  execute(input: Static<S>, requestKey?: string): Promise<unknown>;
};
type Session = { token: string; expiresAt: number };
const sessions = new Map<string, Promise<Session>>();

export function clearTelegramSessions() { sessions.clear(); }

async function bearer(baseUrl: string, apiKey: string, actor: TelegramActor): Promise<string> {
  if (!/^[1-9][0-9]{0,19}$/.test(actor.telegramId)) throw new Error("Invalid Telegram identity");
  const key = `${baseUrl}:${actor.telegramId}`;
  const cached = sessions.get(key);
  if (cached) {
    const session = await cached;
    if (session.expiresAt > Date.now() + 30_000) return session.token;
    sessions.delete(key);
  }
  const pending = (async () => {
    const response = await fetch(`${baseUrl}/api/v1/internal/auth/telegram`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({ telegram_id: actor.telegramId }),
    });
    if (!response.ok) throw new Error("Не удалось войти в журнал. Проверь доступ к боту.");
    const result = await response.json() as { access_token?: string; expires_in?: number };
    if (!result.access_token || !Number.isFinite(result.expires_in) || result.expires_in! <= 0) {
      throw new Error("Invalid authentication response");
    }
    return { token: result.access_token, expiresAt: Date.now() + result.expires_in! * 1000 };
  })();
  if (sessions.size >= 256) sessions.delete(sessions.keys().next().value!);
  sessions.set(key, pending);
  try { return (await pending).token; }
  catch (error) { if (sessions.get(key) === pending) sessions.delete(key); throw error; }
}

export async function userApi(actor: TelegramActor, path: string, method = "GET", body?: unknown,
                              requestKey?: string): Promise<unknown> {
  const baseUrl = process.env.CLIMBING_API_URL;
  const apiKey = process.env.CLIMBING_API_KEY;
  if (!baseUrl || !apiKey) throw new Error("CLIMBING_API_URL and CLIMBING_API_KEY are required");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (requestKey) headers["Idempotency-Key"] = requestKey;
  let response: Response | undefined;
  for (let retry = 0; retry < 2; retry++) {
    headers.Authorization = `Bearer ${await bearer(baseUrl, apiKey, actor)}`;
    response = await fetch(`${baseUrl}${path}`, { method, headers: { ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (response.status !== 401) break;
    sessions.delete(`${baseUrl}:${actor.telegramId}`);
  }
  const result = response!.status === 204 ? null : await response!.json().catch(() => null);
  if (!response!.ok) {
    const detail = result && typeof result === "object" && "detail" in result ? result.detail : response!.statusText;
    throw new Error(`Climbing API: ${typeof detail === "string" ? detail : "Некорректные данные запроса"}`);
  }
  return result;
}

export function usePostgresApi<S extends TSchema>(operation: Operation<S>, actor: TelegramActor): Operation<S> {
  return {
    ...operation,
    async execute(input: Static<S>, requestKey?: string) {
      const startedAt = performance.now();
      const writing = !operation.name.startsWith("get_") && operation.name !== "find_climbing_routes";
      const result = await userApi(actor, `/api/v1/tools/${operation.name}`, "POST", { payload: input },
                                   writing ? requestKey || randomUUID() : undefined);
      console.info("[climbing-journal-metrics]", JSON.stringify({
        tool: operation.name, resultBytes: JSON.stringify(result).length,
        latencyMs: Math.round(performance.now() - startedAt),
      }));
      return result;
    },
  };
}

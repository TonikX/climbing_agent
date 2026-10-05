import type { TSchema, Static } from "typebox";
import { randomUUID } from "node:crypto";

type Operation<S extends TSchema> = {
  name: string;
  label: string;
  description: string;
  parameters: S;
  execute(input: Static<S>, requestKey?: string): Promise<unknown>;
};

export function usePostgresApi<S extends TSchema>(operation: Operation<S>): Operation<S> {
  return {
    ...operation,
    async execute(input: Static<S>, requestKey?: string) {
      const baseUrl = process.env.CLIMBING_API_URL;
      const apiKey = process.env.CLIMBING_API_KEY;
      if (!baseUrl || !apiKey) throw new Error("CLIMBING_API_URL and CLIMBING_API_KEY are required");

      const startedAt = performance.now();
      const headers: Record<string, string> = { "Content-Type": "application/json", "X-API-Key": apiKey };
      if (!operation.name.startsWith("get_") && operation.name !== "find_climbing_routes") {
        headers["Idempotency-Key"] = requestKey || randomUUID();
      }
      const response = await fetch(`${baseUrl}/api/v1/tools/${operation.name}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ payload: input }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = body && typeof body === "object" && "detail" in body ? body.detail : response.statusText;
        throw new Error(`Climbing API: ${String(detail)}`);
      }
      console.info("[climbing-journal-metrics]", JSON.stringify({
        tool: operation.name,
        resultBytes: JSON.stringify(body).length,
        latencyMs: Math.round(performance.now() - startedAt),
      }));
      return body;
    },
  };
}

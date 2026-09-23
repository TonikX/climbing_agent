import type { TSchema, Static } from "typebox";

type Operation<S extends TSchema> = {
  name: string;
  label: string;
  description: string;
  parameters: S;
  execute(input: Static<S>): Promise<unknown>;
};

export function usePostgresApi<S extends TSchema>(operation: Operation<S>): Operation<S> {
  return {
    ...operation,
    async execute(input: Static<S>) {
      const baseUrl = process.env.CLIMBING_API_URL;
      const apiKey = process.env.CLIMBING_API_KEY;
      if (!baseUrl || !apiKey) throw new Error("CLIMBING_API_URL and CLIMBING_API_KEY are required");

      const response = await fetch(`${baseUrl}/api/v1/tools/${operation.name}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify({ payload: input }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = body && typeof body === "object" && "detail" in body ? body.detail : response.statusText;
        throw new Error(`Climbing API: ${String(detail)}`);
      }
      return body;
    },
  };
}

import { afterEach, describe, expect, it, vi } from "vitest";
import { Type } from "typebox";
import { usePostgresApi } from "./api-client.js";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.CLIMBING_API_URL;
  delete process.env.CLIMBING_API_KEY;
});

describe("PostgreSQL API client", () => {
  it("sends a tool command to FastAPI and returns its result", async () => {
    process.env.CLIMBING_API_URL = "http://api:8000";
    process.env.CLIMBING_API_KEY = "secret";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const operation = usePostgresApi({
      name: "example", label: "Example", description: "Example",
      parameters: Type.Object({ value: Type.String() }),
      async execute() { throw new Error("local executor must not run"); },
    });

    await expect(operation.execute({ value: "saved" })).resolves.toEqual({ success: true });
    expect(fetchMock).toHaveBeenCalledWith("http://api:8000/api/v1/tools/example", expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": "secret" },
      body: JSON.stringify({ payload: { value: "saved" } }),
    }));
  });
});

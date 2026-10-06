import { afterEach, describe, expect, it, vi } from "vitest";
import { Type } from "typebox";
import { clearTelegramSessions, usePostgresApi } from "./api-client.js";

afterEach(() => {
  clearTelegramSessions();
  vi.unstubAllGlobals();
  delete process.env.CLIMBING_API_URL;
  delete process.env.CLIMBING_API_KEY;
});

describe("PostgreSQL API client", () => {
  it("sends a tool command to FastAPI and returns its result", async () => {
    process.env.CLIMBING_API_URL = "http://api:8000";
    process.env.CLIMBING_API_KEY = "secret";
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({access_token:"user-token", expires_in:900}) }).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const operation = usePostgresApi({
      name: "example", label: "Example", description: "Example",
      parameters: Type.Object({ value: Type.String() }),
      async execute() { throw new Error("local executor must not run"); },
    }, { telegramId: "42" });

    await expect(operation.execute({ value: "saved" }, "tool-call-123")).resolves.toEqual({ success: true });
    expect(fetchMock).toHaveBeenCalledWith("http://api:8000/api/v1/tools/example", expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer user-token", "Idempotency-Key": "tool-call-123" },
      body: JSON.stringify({ payload: { value: "saved" } }),
    }));
    expect(fetchMock.mock.calls[0][1].body).toBe(JSON.stringify({telegram_id:"42"}));
    await operation.execute({value:"saved"}, "tool-call-123");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps users separate and renews a revoked session with the same write key", async () => {
    process.env.CLIMBING_API_URL = "http://api:8000";
    process.env.CLIMBING_API_KEY = "secret";
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ok:true,json:async()=>({access_token:"a1",expires_in:900})})
      .mockResolvedValueOnce({ok:false,status:401,json:async()=>({})})
      .mockResolvedValueOnce({ok:true,json:async()=>({access_token:"a2",expires_in:900})})
      .mockResolvedValueOnce({ok:true,status:200,json:async()=>({success:true})})
      .mockResolvedValueOnce({ok:true,json:async()=>({access_token:"b",expires_in:900})})
      .mockResolvedValueOnce({ok:true,status:200,json:async()=>({success:true})});
    vi.stubGlobal("fetch",fetchMock);
    const definition = {name:"append",label:"Add",description:"Add",parameters:Type.Object({}),async execute(){return null;}};
    await usePostgresApi(definition,{telegramId:"42"}).execute({},"retry-key");
    await usePostgresApi(definition,{telegramId:"43"}).execute({},"retry-key");
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer a1");
    expect(fetchMock.mock.calls[3][1].headers.Authorization).toBe("Bearer a2");
    expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toBe("retry-key");
    expect(fetchMock.mock.calls[3][1].headers["Idempotency-Key"]).toBe("retry-key");
    expect(fetchMock.mock.calls[4][1].body).toBe(JSON.stringify({telegram_id:"43"}));
    expect(fetchMock.mock.calls[5][1].headers.Authorization).toBe("Bearer b");
  });
});

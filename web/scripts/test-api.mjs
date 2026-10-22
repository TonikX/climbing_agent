import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
const source = await readFile(
  new URL("../src/api.ts", import.meta.url),
  "utf8",
);
const js = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const api = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);
test("dashboard reads flat DTO, passes filters and cookies without a bearer key", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    return new Response(
      JSON.stringify(
        url.includes("/month?")
          ? {
              trainingsCount: 2,
              routesCount: 4,
              completedRoutes: 1,
              grades: [{ grade: "6B", routesCount: 4 }],
            }
          : { periods: [] },
      ),
      { status: 200 },
    );
  };
  try {
    const result = await api.dashboard(
      { from: "2026-10-01", to: "2026-10-22", grade: "6B+" },
      new AbortController().signal,
    );
    assert.equal(result.summary.routesCount, 4);
    assert.equal(result.summary.trainingsCount, 2);
    assert.equal(result.grades[0].grade, "6B");
    assert.equal(calls.length, 2);
    for (const [url, options] of calls) {
      assert.equal(options.credentials, "include");
      assert.equal(options.headers.Authorization, undefined);
      const q = new URL(url, "http://localhost").searchParams;
      assert.equal(q.get("grade"), "6B+");
      assert.equal(q.get("date_from"), "2026-10-01");
    }
  } finally {
    globalThis.fetch = original;
  }
});
test("unauthorized response becomes an explicit login error", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("{}", { status: 401 });
  try {
    await assert.rejects(
      api.request("/me"),
      (e) => e instanceof api.ApiError && e.status === 401,
    );
  } finally {
    globalThis.fetch = original;
  }
});

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createJournalService } from "./application/journal.js";
import { createJsonStore } from "./storage/json-store.js";

// Exercise the real application service and storage without loading OpenClaw.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "climbing-journal-test-"));
const journal = createJournalService(createJsonStore(directory));
const handlers = Object.values(journal);
type OperationName = keyof typeof journal;
const run = <K extends OperationName>(name: K, input: Parameters<typeof journal[K]["execute"]>[0]) =>
  journal[name].execute(input as never) as ReturnType<typeof journal[K]["execute"]>;
const read = (name: string) => fs.existsSync(path.join(directory, `${name}.json`))
  ? JSON.parse(fs.readFileSync(path.join(directory, `${name}.json`), "utf8")) : [];
const write = (name: string, values: any[]) => fs.writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(values));
const alice = { name: "Alex", externalRefs: [{ system: "telegram", id: "alice" }] };
const bob = { name: "Alex", externalRefs: [{ system: "telegram", id: "bob" }] };
const date = "2026-09-19";
const start = (extra: any = {}) => run("start_climbing_training", { user: alice, date, ...extra });
const append = (attempt: any, extra: any = {}) => run("append_climbing_attempt", { user: alice, date, attempt, ...extra });
const summary = (routes: any[], extra: any = {}) => run("save_climbing_training", { user: alice, date, mergeIntoActive: true, routes, ...extra });
const current = () => read("trainings")[0];

beforeEach(() => {
  for (const file of fs.readdirSync(directory)) fs.rmSync(path.join(directory, file), { recursive: true });
});
afterAll(() => fs.rmSync(directory, { recursive: true }));

describe("JSON MVP regressions", () => {
  it("registers all eight real tools and uses integer attempts/limits", () => {
    expect(handlers.map((tool: any) => tool.name)).toEqual([
      "start_climbing_training", "append_climbing_attempt", "save_climbing_training", "update_climbing_training",
      "finish_climbing_training", "upsert_climbing_gear", "find_climbing_routes", "get_climbing_trainings",
    ]);
    expect(journal.append_climbing_attempt.parameters.properties.attempt.properties.attempts.type).toBe("integer");
    expect(journal.get_climbing_trainings.parameters.properties.limit.type).toBe("integer");
  });
  it("keeps unnamed routes as snapshots and never deduplicates append", async () => {
    await append({ grade: "6A", result: "send", attempts: 1 });
    await append({ grade: "6A", result: "send", attempts: 1 });
    expect(read("trainings")).toHaveLength(1);
    expect(current().routes).toHaveLength(2);
    expect(current().routes[0].style).toBe("unknown");
    expect(read("routes")).toEqual([]);
  });
  it("merges unambiguous summaries without duplicating events", async () => {
    await append({ grade: "6A", result: "send", attempts: 1 });
    await append({ grade: "6B", result: "send", style: "redpoint", attempts: 2 });
    const routes = [{ grade: "6A", attempts: 1 }, { grade: "6B", attempts: 2 }];
    await summary(routes, { durationMinutes: 180 });
    await summary(routes);
    expect(current().routes).toHaveLength(2);
    expect(current().durationMinutes).toBe(180);
    expect(current().routes[0].result).toBe("send");
    expect(current().routes[1].style).toBe("redpoint");
  });
  it("does not collapse repeated unnamed routes or aggregate attempts", async () => {
    await append({ grade: "6A", attempts: 1 });
    await append({ grade: "6A", attempts: 1 });
    await summary([{ grade: "6A", attempts: 2 }]);
    expect(current().routes.map((route: any) => route.attempts)).toEqual([1, 1, 2]);
  });
  it("does not merge two summary entries into one event", async () => {
    await append({ grade: "6A" });
    await summary([{ grade: "6A" }, { grade: "6A" }]);
    expect(current().routes).toHaveLength(3);
  });
  it("keeps repeated entries in a summary when active routes are empty", async () => {
    await start();
    await summary([{ grade: "6A" }, { grade: "6A" }]);
    expect(current().routes).toHaveLength(2);
  });
  it("refines a uniquely matched unnamed route with name and sector", async () => {
    await append({ grade: "6A", result: "send" });
    await summary([{ name: "Heart", grade: "6A" }], { area: { name: "Area" }, sector: { name: "Sector" } });
    expect(current().routes).toHaveLength(1);
    expect(current().routes[0].routeSnapshot.name).toBe("Heart");
    expect(current().routes[0].routeSnapshot.sectorId).toBeTruthy();
    expect(read("routes")).toHaveLength(1);
  });
  it("does not combine conflicting names, sectors or belay modes", async () => {
    await start({ area: { name: "Area" }, sector: { name: "One" } });
    await append({ name: "Heart", grade: "6A", belay: "lead" });
    await summary([{ name: "Heart", grade: "6A", belay: "top_rope" }]);
    await summary([{ name: "Other", grade: "6A" }]);
    await summary([{ name: "Heart", grade: "6A", sector: { name: "Two" } }]);
    expect(current().routes).toHaveLength(4);
  });
  it("preserves snapshot fields when later input omits them", async () => {
    await append({ name: "Heart", grade: "6A", notes: "original", result: "send" });
    await summary([{ grade: "6A" }]);
    expect(current().routes).toHaveLength(1);
    expect(current().routes[0].routeSnapshot.name).toBe("Heart");
    expect(current().routes[0].notes).toBe("original");
  });
  it("keeps same-name Telegram users separate and closes only the right session", async () => {
    await start();
    await start({ user: bob });
    await start();
    expect(read("users")).toHaveLength(2);
    expect(read("trainings").map((training: any) => training.status)).toEqual(["completed", "active", "active"]);
    await expect(run("finish_climbing_training", { user: { name: "Alex" } })).rejects.toThrow("Ambiguous");
  });
  it("rejects unknown or conflicting explicit user identities", async () => {
    await start();
    const id = read("users")[0].id;
    await expect(start({ user: { id: "missing", name: "Alex" } })).rejects.toThrow("does not exist");
    await expect(start({ user: { id, ...bob } })).rejects.toThrow("Conflicting");
    expect(read("trainings")).toHaveLength(1);
  });
  it("returns no history for an unknown name and rejects ambiguous names", async () => {
    await start();
    expect(await run("get_climbing_trainings", { userName: "Missing" })).toEqual({ count: 0, trainings: [] });
    await start({ user: bob });
    await expect(run("get_climbing_trainings", { userName: "Alex" })).rejects.toThrow("Ambiguous");
    expect((await run("get_climbing_trainings", { userId: read("users")[0].id })).count).toBe(1);
  });
  it("rejects updates to another user's training", async () => {
    const training = await start();
    await expect(run("update_climbing_training", { user: bob, trainingId: training.trainingId, notes: "wrong" })).rejects.toThrow("No matching");
    expect(current().notes).toBeUndefined();
    expect(read("users")).toHaveLength(1);
  });
  it("rejects foreign gear IDs on every write path", async () => {
    const { gear } = await run("upsert_climbing_gear", { user: alice, gear: { type: "shoes", brand: "Brand" } });
    await expect(run("upsert_climbing_gear", { user: bob, gear: { id: gear.id, type: "shoes" } })).rejects.toThrow("Unknown gear");
    await expect(start({ user: bob, gearIds: [gear.id] })).rejects.toThrow("does not belong");
    await start({ user: bob });
    await expect(run("update_climbing_training", { user: bob, gearIds: [gear.id] })).rejects.toThrow("does not belong");
    await expect(summary([], { user: bob, gearIds: [gear.id] })).rejects.toThrow("does not belong");
    expect(read("gear")).toHaveLength(1);
  });
  it("standalone summary does not inherit active location or modify it", async () => {
    await start({ area: { name: "Area" }, sector: { name: "Sector" } });
    await summary([{ grade: "6A" }], { mergeIntoActive: false, date: "2026-09-18" });
    const saved = read("trainings");
    expect(saved[0].status).toBe("active");
    expect(saved[1].status).toBe("completed");
    expect(saved[1].areaId).toBeUndefined();
    expect(saved[1].sectorIds).toEqual([]);
  });
  it("inherits active area before resolving a newly named sector", async () => {
    await start({ area: { name: "Area" } });
    await append({ grade: "6A" }, { sector: { name: "Sector" } });
    expect(read("sectors")[0].areaId).toBe(current().areaId);
  });
  it("preserves metadata sectors when summary contains no routes", async () => {
    await start({ area: { name: "Area" }, sector: { name: "Sector" } });
    const id = current().sectorIds[0];
    await summary([]);
    expect(current().sectorIds).toContain(id);
    await summary([], { mergeIntoActive: false, area: { name: "Area" }, sector: { name: "Sector" } });
    expect(read("trainings")[1].sectorIds).toContain(id);
  });
  it("rejects a different session date instead of silently merging", async () => {
    await start();
    await expect(append({ grade: "6A" }, { date: "2026-09-20" })).rejects.toThrow("different date");
    await expect(summary([], { date: "2026-09-20" })).rejects.toThrow("date differs");
    expect(current().routes).toEqual([]);
  });
  it("resolves routeId context and preserves catalogue grades", async () => {
    write("areas", [{ id: "area_a", name: "Area" }]);
    write("sectors", [{ id: "sector_a", name: "Sector", areaId: "area_a" }]);
    write("routes", [{ id: "route_a", name: "Heart", grade: "6A", sectorId: "sector_a" }]);
    await append({ routeId: "route_a", grade: "6B" });
    expect(current().routes[0].routeSnapshot).toMatchObject({ areaId: "area_a", sectorId: "sector_a", grade: "6B" });
    expect(read("routes")[0].grade).toBe("6A");
    expect((await run("get_climbing_trainings", { grade: "6B" })).count).toBe(1);
  });
  it("rejects catalogue ID mismatches without partial writes", async () => {
    await start({ area: { name: "Area" }, sector: { name: "Sector" } });
    const before = fs.readFileSync(path.join(directory, "trainings.json"), "utf8");
    await expect(start({ area: { id: "absent", name: "Area" } })).rejects.toThrow("Unknown area");
    await expect(append({ grade: "6A" }, { area: { name: "Other" }, sector: { id: read("sectors")[0].id } })).rejects.toThrow("does not belong");
    expect(fs.readFileSync(path.join(directory, "trainings.json"), "utf8")).toBe(before);
    expect(read("areas")).toHaveLength(1);
  });
  it("stages changes so invalid attempts do not create an empty session", async () => {
    await expect(append({ routeId: "missing" })).rejects.toThrow("does not exist");
    expect(read("trainings")).toEqual([]);
    expect(read("users")).toEqual([]);
  });
  it("keeps a foreign process lock and never writes while it exists", async () => {
    fs.mkdirSync(path.join(directory, ".climbing-journal.lock"));
    await expect(start()).rejects.toThrow("busy");
    expect(fs.existsSync(path.join(directory, ".climbing-journal.lock"))).toBe(true);
    expect(read("users")).toEqual([]);
  });
  it("preserves corrupt or empty JSON and releases its own lock after failure", async () => {
    const file = path.join(directory, "trainings.json");
    for (const raw of ["", "{broken", "{}"] ) {
      fs.writeFileSync(file, raw);
      await expect(start()).rejects.toThrow();
      expect(fs.readFileSync(file, "utf8")).toBe(raw);
      expect(read("users")).toEqual([]);
      expect(fs.existsSync(path.join(directory, ".climbing-journal.lock"))).toBe(false);
    }
  });
  it("preserves old data if atomic rename fails and cleans temporary files", async () => {
    await start();
    const before = fs.readFileSync(path.join(directory, "trainings.json"), "utf8");
    const rename = vi.spyOn(fs, "renameSync").mockImplementation(() => { throw new Error("disk error"); });
    try { await expect(append({ grade: "6A" })).rejects.toThrow("disk error"); }
    finally { rename.mockRestore(); }
    expect(fs.readFileSync(path.join(directory, "trainings.json"), "utf8")).toBe(before);
    expect(fs.readdirSync(directory).some((name) => name.endsWith(".tmp") || name.endsWith(".lock"))).toBe(false);
  });
  it("records only supplied weather and finishes with final metadata", async () => {
    await start();
    expect(current().weather).toBeUndefined();
    await run("update_climbing_training", { user: alice, weather: { temperatureC: 12, wind: "strong" } });
    await summary([], { weather: { rockCondition: "dry" } });
    await run("finish_climbing_training", { user: alice, durationMinutes: 180, notes: "done" });
    expect(current()).toMatchObject({ status: "completed", durationMinutes: 180, notes: "done", weather: { temperatureC: 12, wind: "strong", rockCondition: "dry" } });
  });
  it("finds a training by its sector even before the first route", async () => {
    await start({ area: { name: "Area" }, sector: { name: "Sector" } });
    await summary([]);
    await summary([]);
    const history = await run("get_climbing_trainings", { sector: "Sector" });
    expect(history.count).toBe(1);
    expect(history.trainings[0].sectors).toHaveLength(1);
    expect(current().sectorIds).toHaveLength(1);
  });
  it("reuses an unambiguous area when country was omitted", async () => {
    await start({ area: { name: "Area", country: "RU" } });
    await append({ grade: "6A" }, { area: { name: "Area" } });
    expect(read("areas")).toHaveLength(1);
  });
  it("rejects conflicting references even without an internal user ID", async () => {
    await start();
    await expect(start({ user: { name: "Alex", externalRefs: [...alice.externalRefs, ...bob.externalRefs] } })).rejects.toThrow("Conflicting");
    expect(read("users")[0].externalRefs).toEqual(alice.externalRefs);
  });
});

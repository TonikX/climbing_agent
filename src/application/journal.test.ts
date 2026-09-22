import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, it } from "vitest";
import { createJournalService } from "./journal.js";
import { createJsonStore } from "../storage/json-store.js";

const directories: string[] = [];
function journal() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "journal-service-"));
  directories.push(directory);
  return createJournalService(createJsonStore(directory));
}
afterEach(() => {
  for (const directory of directories.splice(0)) fs.rmSync(directory, { recursive: true });
});

it("supports the full session lifecycle without the OpenClaw host", async () => {
  const service = journal();
  const user = { name: "Service user" };
  const date = "2026-09-20";
  const started = await service.start_climbing_training.execute({ user, date });
  await service.append_climbing_attempt.execute({ user, date, attempt: { grade: "6A", result: "send" } });
  await service.save_climbing_training.execute({ user, date, mergeIntoActive: true, routes: [{ grade: "6A", attempts: 1 }] });
  await service.finish_climbing_training.execute({ user, durationMinutes: 90 });
  const history = await service.get_climbing_trainings.execute({ userName: user.name });
  expect(history.count).toBe(1);
  expect(history.trainings[0]).toMatchObject({ id: started.trainingId, status: "completed", durationMinutes: 90 });
  expect(history.trainings[0].routes).toHaveLength(1);
});

it("keeps separately configured service instances isolated", async () => {
  const first = journal();
  const second = journal();
  await first.start_climbing_training.execute({ user: { name: "First" }, date: "2026-09-20" });
  expect((await second.get_climbing_trainings.execute({})).count).toBe(0);
  expect((await first.get_climbing_trainings.execute({})).count).toBe(1);
});

it("stores test attempts but excludes them from normal history", async () => {
  const service = journal();
  const user = { name: "Test marker user" };
  const date = "2026-09-22";
  await service.append_climbing_attempt.execute({
    user,
    date,
    attempt: { name: "Test route", grade: "6B", result: "send", isTest: true },
  });

  const normal = await service.get_climbing_trainings.execute({ userName: user.name });
  expect(normal.trainings[0].routes).toEqual([]);

  const diagnostic = await service.get_climbing_trainings.execute({
    userName: user.name,
    includeTest: true,
  });
  expect(diagnostic.trainings[0].routes).toHaveLength(1);
  expect(diagnostic.trainings[0].routes[0].isTest).toBe(true);
});

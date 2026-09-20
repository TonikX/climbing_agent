import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { JsonObject } from "../domain/records.js";
import type { Collection, JournalStore } from "./store.js";

export function createJsonStore(directory: string): JournalStore {
  let pendingWrites: Map<Collection, JsonObject[]> | undefined;
  const filePath = (collection: Collection) => path.join(directory, `${collection}.json`);
// All tool operations are synchronous inside this lock. A busy/stale lock fails
// closed; never remove another process's lock automatically.
function transaction<T>(operation: () => T): T {
  ensureDataDir();
  const lock = path.join(directory, ".climbing-journal.lock");
  try {
    fs.mkdirSync(lock);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("Climbing journal storage is busy or has a stale lock; retry or inspect the lock before removing it.");
    }
    throw error;
  }
  pendingWrites = new Map();
  try {
    const result = operation();
    // Validation errors commit nothing. Each file replacement is atomic;
    // a process crash across multiple file replacements is not a DB transaction.
    const writes = [...pendingWrites].sort(([a], [b]) => Number(a === "trainings") - Number(b === "trainings"));
    for (const [file, records] of writes) writeArrayAtomic(filePath(file), records);
    return result;
  } finally {
    pendingWrites = undefined;
    fs.rmdirSync(lock);
  }
}

function ensureDataDir() {
  fs.mkdirSync(directory, { recursive: true });
}

function readArray(collection: Collection): JsonObject[] {
  const file = filePath(collection);
  ensureDataDir();
  const staged = pendingWrites?.get(collection);
  if (staged) return structuredClone(staged);

  if (!fs.existsSync(file)) {
    return [];
  }

  const raw = fs.readFileSync(file, "utf8").trim();

  if (!raw) {
    throw new Error(`${file} is empty; refusing to overwrite potentially damaged data`);
  }

  const parsed = JSON.parse(raw);

  if (!Array.isArray(parsed)) {
    throw new Error(`${file} must contain a JSON array`);
  }

  return parsed;
}

function writeArray(collection: Collection, data: JsonObject[]) {
  if (!pendingWrites) throw new Error("Storage write requires a lock");
  pendingWrites.set(collection, structuredClone(data));
}

function writeArrayAtomic(file: string, data: JsonObject[]) {
  const tmp = `${file}.${process.pid}.${randomUUID()}.tmp`;
  try {
    const fd = fs.openSync(tmp, "wx", 0o600);
    try {
      fs.writeFileSync(fd, JSON.stringify(data, null, 2) + "\n", "utf8");
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    fs.renameSync(tmp, file);
  } finally {
    if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
  }
}


  return { transaction, read: readArray, write: writeArray };
}

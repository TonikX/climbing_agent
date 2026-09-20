import type { JsonObject } from "../domain/records.js";

export const collections = {
  users: "users", areas: "areas", sectors: "sectors", routes: "routes",
  gear: "gear", trainings: "trainings",
} as const;
export type Collection = typeof collections[keyof typeof collections];

// Synchronous unit of work for the current JSON MVP. This is deliberately not a
// SQL repository contract; async repositories and typed entities precede SQL.
export interface JournalStore {
  transaction<T>(operation: () => T): T;
  read(collection: Collection): JsonObject[];
  write(collection: Collection, records: JsonObject[]): void;
}

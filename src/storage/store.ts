import type { JsonObject } from "../domain/records.js";

export const collections = {
  users: "users", areas: "areas", sectors: "sectors", routes: "routes",
  gear: "gear", trainings: "trainings",
} as const;
export type Collection = typeof collections[keyof typeof collections];

// Contract used by the schema/domain module. Production execution is delegated
// to FastAPI and PostgreSQL by src/storage/api-client.ts.
export interface JournalStore {
  transaction<T>(operation: () => T): T;
  read(collection: Collection): JsonObject[];
  write(collection: Collection, records: JsonObject[]): void;
}

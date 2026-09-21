import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalService } from "./application/journal.js";
import { createJsonStore } from "./storage/json-store.js";
import { syncJournalSnapshot } from "./storage/api-sync.js";

const store = createJsonStore(
  process.env.CLIMBING_JOURNAL_DATA_DIR ?? "/root/.openclaw/workspace/data",
);
const journal = createJournalService(store);
const mutations = new Set([
  "start_climbing_training", "append_climbing_attempt", "save_climbing_training",
  "update_climbing_training", "finish_climbing_training", "upsert_climbing_gear",
]);

function withDatabaseSync<T extends { name: string; execute(input: never): Promise<unknown> }>(operation: T): T {
  if (!mutations.has(operation.name)) return operation;
  return {
    ...operation,
    async execute(input: never) {
      const result = await operation.execute(input);
      await syncJournalSnapshot(store);
      return result;
    },
  } as T;
}

export default defineToolPlugin({
  id: "climbing-journal",
  name: "Climbing Journal",
  description: "Structured multi-user climbing journal with active training sessions, routes, areas, sectors, gear and user-reported weather.",
  tools: (tool) => [
    tool(withDatabaseSync(journal.start_climbing_training)),
    tool(withDatabaseSync(journal.append_climbing_attempt)),
    tool(withDatabaseSync(journal.save_climbing_training)),
    tool(withDatabaseSync(journal.update_climbing_training)),
    tool(withDatabaseSync(journal.finish_climbing_training)),
    tool(withDatabaseSync(journal.upsert_climbing_gear)),
    tool(journal.find_climbing_routes),
    tool(journal.get_climbing_trainings),
  ],
});

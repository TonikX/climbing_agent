import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalService } from "./application/journal.js";
import { usePostgresApi } from "./storage/api-client.js";

// createJournalService remains the single source of tool schemas. Its local
// executors are replaced below, so the no-op store is never read or written.
const journal = createJournalService({
  transaction: (operation) => operation(),
  read: () => [],
  write: () => { throw new Error("Local journal storage is disabled"); },
});

export default defineToolPlugin({
  id: "climbing-journal",
  name: "Climbing Journal",
  description: "Structured multi-user climbing journal with active training sessions, routes, areas, sectors, gear and user-reported weather.",
  tools: (tool) => [
    tool(usePostgresApi(journal.start_climbing_training)),
    tool(usePostgresApi(journal.append_climbing_attempt)),
    tool(usePostgresApi(journal.save_climbing_training)),
    tool(usePostgresApi(journal.update_climbing_training)),
    tool(usePostgresApi(journal.finish_climbing_training)),
    tool(usePostgresApi(journal.upsert_climbing_gear)),
    tool(usePostgresApi(journal.find_climbing_routes)),
    tool(usePostgresApi(journal.get_climbing_trainings)),
  ],
});

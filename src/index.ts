import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalService } from "./application/journal.js";
import { createJsonStore } from "./storage/json-store.js";

const journal = createJournalService(createJsonStore(
  process.env.CLIMBING_JOURNAL_DATA_DIR ?? "/root/.openclaw/workspace/data",
));

export default defineToolPlugin({
  id: "climbing-journal",
  name: "Climbing Journal",
  description: "Structured multi-user climbing journal with active training sessions, routes, areas, sectors, gear and user-reported weather.",
  tools: (tool) => [
    tool(journal.start_climbing_training),
    tool(journal.append_climbing_attempt),
    tool(journal.save_climbing_training),
    tool(journal.update_climbing_training),
    tool(journal.finish_climbing_training),
    tool(journal.upsert_climbing_gear),
    tool(journal.find_climbing_routes),
    tool(journal.get_climbing_trainings),
  ],
});

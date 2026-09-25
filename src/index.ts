import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalTools } from "./application/journal.js";
import { registerTelegramMenu } from "./application/telegram-menu.js";
import { usePostgresApi } from "./storage/api-client.js";

const journal = createJournalTools();

const plugin = defineToolPlugin({
  id: "climbing-journal",
  name: "Climbing Journal",
  description: "Structured multi-user climbing journal with active training sessions, routes, areas, sectors, gear and user-reported weather.",
  tools: (tool) => [
    tool(usePostgresApi(journal.start_climbing_training)),
    tool(usePostgresApi(journal.append_climbing_attempt)),
    tool(usePostgresApi(journal.update_climbing_attempt)),
    tool(usePostgresApi(journal.delete_climbing_attempt)),
    tool(usePostgresApi(journal.finish_climbing_training)),
    tool(usePostgresApi(journal.get_current_climbing_training)),
    tool(usePostgresApi(journal.get_climbing_statistics)),
    tool(usePostgresApi(journal.save_climbing_training)),
    tool(usePostgresApi(journal.update_climbing_training)),
    tool(usePostgresApi(journal.upsert_climbing_gear)),
    tool(usePostgresApi(journal.find_climbing_routes)),
    tool(usePostgresApi(journal.get_climbing_trainings)),
  ],
});

const registerTools = plugin.register;
plugin.register = async (api) => {
  await registerTools(api);
  registerTelegramMenu(api);
};

export default plugin;

import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalTools } from "./application/journal.js";
import { formatStatisticsResult, registerTelegramMenu } from "./application/telegram-menu.js";
import { usePostgresApi } from "./storage/api-client.js";

const journal = createJournalTools();
const statistics = usePostgresApi(journal.get_climbing_statistics);
type StatisticsInput = Parameters<typeof statistics.execute>[0];

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
    tool({
      name: journal.get_climbing_statistics.name,
      label: journal.get_climbing_statistics.label,
      description: `${journal.get_climbing_statistics.description} The result is formatted and delivered directly; do not add another response.`,
      parameters: journal.get_climbing_statistics.parameters,
      factory({ toolContext }) {
        return {
          name: journal.get_climbing_statistics.name,
          label: journal.get_climbing_statistics.label,
          description: journal.get_climbing_statistics.description,
          parameters: journal.get_climbing_statistics.parameters,
          async execute(_toolCallId, params) {
            const input = params as StatisticsInput;
            const result = await statistics.execute(input);
            const formatted = formatStatisticsResult(input.scope, result);
            if (toolContext.delivery) {
              await toolContext.delivery.send({ text: formatted });
              return {
                content: [{ type: "text" as const, text: "Статистика отправлена пользователю." }],
                details: result,
                terminate: true,
              };
            }
            return {
              content: [{ type: "text" as const, text: formatted }],
              details: result,
            };
          },
        };
      },
    }),
    tool(usePostgresApi(journal.set_climbing_test_mode)),
    tool(usePostgresApi(journal.save_climbing_training)),
    tool(usePostgresApi(journal.update_climbing_training)),
    tool(usePostgresApi(journal.upsert_climbing_gear)),
    tool(usePostgresApi(journal.find_climbing_routes)),
    tool(usePostgresApi(journal.get_climbing_trainings)),
  ],
});

const registerTools = plugin.register;
plugin.register = (api) => {
  registerTools(api);
  registerTelegramMenu(api);
};

export default plugin;

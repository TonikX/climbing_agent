import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createJournalTools, type JournalOperation } from "./application/journal.js";
import { formatStatisticsResult, registerTelegramMenu } from "./application/telegram-menu.js";
import { usePostgresApi } from "./storage/api-client.js";

import { bindTelegramUser } from "./application/telegram-identity.js";

const journal = createJournalTools();
const plugin = defineToolPlugin({
  id: "climbing-journal",
  name: "Climbing Journal",
  description: "Structured multi-user climbing journal with active training sessions, routes, areas, sectors, gear and user-reported weather.",
  tools: (tool) => Object.values(journal).map((operation) => tool({
    name: operation.name,
    label: operation.label,
    description: operation.description,
    parameters: operation.parameters,
    factory({ toolContext }) {
      return {
        name: operation.name,
        label: operation.label,
        description: operation.description,
        parameters: operation.parameters,
        async execute(toolCallId, params) {
          const raw = params as Record<string, unknown>;
          const input = bindTelegramUser(operation.name === "get_climbing_trainings"
            ? { user: {}, ...raw } : raw, toolContext);
          const transport = usePostgresApi(operation as JournalOperation);
          const result = await transport.execute(input, toolCallId);
          if (operation.name === "get_climbing_statistics") {
            const formatted = formatStatisticsResult(String(input.scope), result);
            if (toolContext.delivery) {
              await toolContext.delivery.send({ text: formatted });
              return {
                content: [{ type: "text" as const, text: "Статистика отправлена пользователю." }],
                details: result, terminate: true,
              };
            }
            return { content: [{ type: "text" as const, text: formatted }], details: result };
          }
          return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result };
        },
      };
    },
  })),
});

const registerTools = plugin.register;
plugin.register = (api) => {
  registerTools(api);
  registerTelegramMenu(api);
};

export default plugin;

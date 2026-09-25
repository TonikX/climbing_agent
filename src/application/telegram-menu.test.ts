import { describe, expect, it, vi } from "vitest";
import { registerTelegramMenu } from "./telegram-menu.js";

describe("Telegram journal menu", () => {
  it("registers a journal command with direct action buttons", async () => {
    const commands: Array<Record<string, unknown>> = [];
    registerTelegramMenu({ registerCommand: (command: unknown) => commands.push(command as Record<string, unknown>) } as never);

    expect(commands.map((command) => command.name)).toEqual([
      "journal", "another_attempt", "current_training", "week_stats", "finish_training",
    ]);
    const journal = commands[0];
    const result = await (journal.handler as () => Promise<Record<string, unknown>>)();
    expect(result.text).toBe("Что сделать?");
    expect(result.interactive).toMatchObject({
      blocks: [{
        type: "buttons",
        buttons: [
          { action: { type: "command", command: "/another_attempt" } },
          { action: { type: "command", command: "/current_training" } },
          { action: { type: "command", command: "/week_stats" } },
          { action: { type: "command", command: "/finish_training" } },
        ],
      }],
    });
    vi.restoreAllMocks();
  });
});

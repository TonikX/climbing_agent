import { describe, expect, it } from "vitest";
import entry from "./index.js";
import { getToolPluginMetadata } from "openclaw/plugin-sdk/tool-plugin";

describe("climbing-journal host metadata", () => {
  it("declares the eight journal tools through the real OpenClaw SDK", () => {
    expect(getToolPluginMetadata(entry)?.tools.map((tool) => tool.name)).toEqual([
      "start_climbing_training", "append_climbing_attempt", "save_climbing_training",
      "update_climbing_training", "finish_climbing_training", "upsert_climbing_gear",
      "find_climbing_routes", "get_climbing_trainings",
    ]);
  });
});

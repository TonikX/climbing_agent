import type { JournalStore } from "./store.js";
import { collections } from "./store.js";

export async function syncJournalSnapshot(store: JournalStore): Promise<void> {
  const apiUrl = process.env.CLIMBING_API_URL;
  const apiKey = process.env.CLIMBING_API_KEY;
  if (!apiUrl || !apiKey) {
    throw new Error("CLIMBING_API_URL and CLIMBING_API_KEY are required for database persistence");
  }

  const snapshot = Object.fromEntries(
    Object.values(collections).map((collection) => [collection, store.read(collection)]),
  );
  const baseUrl = apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl;
  const response = await fetch(`${baseUrl}/api/v1/journal/snapshot`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body: JSON.stringify(snapshot),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Database sync failed (${response.status}): ${detail.slice(0, 500)}`);
  }
}

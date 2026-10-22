export type StatisticsView = "simple" | "advanced";
export const statisticsViewKey = "climbing.statistics.view";
const valid = (value: string | null): value is StatisticsView =>
  value === "simple" || value === "advanced";

export function readStatisticsView(
  search: string,
  saved: () => string | null,
): StatisticsView {
  const requested = new URLSearchParams(search).get("view");
  if (valid(requested)) return requested;
  try {
    const value = saved();
    if (valid(value)) return value;
  } catch {
    // The URL still works when browser storage is unavailable.
  }
  return "simple";
}

export type StatisticsView = "simple" | "advanced";
const valid = (value: string | null): value is StatisticsView =>
  value === "simple" || value === "advanced";

export function readStatisticsView(search: string): StatisticsView {
  const requested = new URLSearchParams(search).get("view");
  if (valid(requested)) return requested;
  return "simple";
}

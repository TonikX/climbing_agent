export type Summary = {
  trainingsCount?: number;
  routesCount?: number;
  attemptsCount?: number;
  completedRoutes?: number;
  reachedTopRoutes?: number;
  completionRate?: number;
  maxAttemptedGrade?: string | null;
  maxReachedTopGrade?: string | null;
  maxCompletedGrade?: string | null;
};
export type Grade = Summary & { grade: string };
export type Period = Summary & { period: string };
export type Attempt = {
  id: string;
  sequence: number;
  attempts: number;
  reached_top: boolean | null;
  clean_ascent: boolean | null;
  style: string;
  belay: string;
  falls: number | null;
  hangs: number | null;
  notes: string | null;
  is_test: boolean;
  route_snapshot: {
    name?: string;
    grade?: string;
    areaId?: string;
    sectorId?: string;
  };
};
export type Training = {
  id: string;
  local_date: string;
  status: string;
  environment: string;
  duration_minutes: number | null;
  notes: string | null;
  attempts: Attempt[];
  demoLocation?: string;
  demoSector?: string;
};
export type User = { name: string; timezone: string; status: string };
export type Filters = { from: string; to: string; grade: string };
export class ApiError extends Error {
  constructor(public status: number) {
    super(
      status === 401
        ? "Войдите, чтобы увидеть свою статистику."
        : status === 403
          ? "Доступ к журналу пока не подтверждён."
          : "Не удалось загрузить данные. Попробуйте ещё раз.",
    );
  }
}
export async function request<T>(
  path: string,
  signal?: AbortSignal,
  mutation?: { csrf: string; method: "POST" },
): Promise<T> {
  const r = await fetch("/api/v1" + path, {
    credentials: "include",
    signal,
    method: mutation?.method ?? "GET",
    headers: {
      Accept: "application/json",
      ...(mutation ? { "X-CSRF-Token": mutation.csrf } : {}),
    },
  });
  if (!r.ok) throw new ApiError(r.status);
  if (r.status === 204) return undefined as T;
  return r.json();
}
export type BrowserSession = {
  user: User;
  csrfToken: string;
  expiresAt: string;
};
export function query(f: Filters) {
  const q = new URLSearchParams({ date_from: f.from, date_to: f.to });
  if (f.grade) q.set("grade", f.grade);
  return q;
}
export async function dashboard(f: Filters, signal: AbortSignal) {
  const q = query(f);
  const [month, progress] = await Promise.all([
    request<Summary & { grades: Grade[] }>("/statistics/month?" + q, signal),
    request<{ periods: Period[] }>("/statistics/progress?" + q, signal),
  ]);
  return {
    summary: month,
    grades: month.grades ?? [],
    periods: progress.periods ?? [],
  };
}
export const trainingPage = (cursor: string | null, signal: AbortSignal) =>
  request<{ items: Training[]; next_cursor: string | null }>(
    "/trainings?include_test=false&limit=12" +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    signal,
  );

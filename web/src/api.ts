export type BelayReachedCounts = { total: number; clean: number; nonClean: number; unknownClean: number };
export type Summary = {
  ascentsCount?: number;
  ascentsByBelay?: Partial<Record<"lead" | "top_rope" | "auto_belay" | "bouldering" | "unknown", BelayReachedCounts>>;
  reachedByBelay?: Partial<Record<"lead" | "top_rope" | "auto_belay" | "bouldering" | "unknown", BelayReachedCounts>>;
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
export type PyramidBucket =
  "onsight" | "flash" | "redpoint" | "top_rope" | "other_clean" | "not_clean";
export type AscentStyle =
  | "onsight"
  | "flash"
  | "redpoint"
  | "with_falls"
  | "with_hangs"
  | "not_reached"
  | "unknown";
export type Grade = Summary & {
  styles?: Record<AscentStyle, number>;
  belays?: Record<string, number>;
  grade: string;
  pyramid?: Record<PyramidBucket, number>;
};
export type GradeAscent = {
  trainingId: string;
  date: string;
  routeSessionKey: string;
  route: { name: string | null; grade: string | null };
  location: { id: string; name: string; region: string | null } | null;
  sector: { id: string; name: string } | null;
  bucket: PyramidBucket;
  style: string;
  belay: string;
  cleanAscent: boolean | null;
  reachedTop: boolean | null;
  attemptsCount: number;
  attempts: Attempt[];
};
export type GradeAscentsPage = {
  items: GradeAscent[];
  total: number;
  nextOffset: number | null;
};
export function gradeAscents(
  filters: Filters,
  grade: string,
  style: AscentStyle | null,
  offset: number,
  signal: AbortSignal,
  belay?: string,
) {
  const q = query({ ...filters, grade });
  if (style) q.set("group_style", style);
  if (belay) q.set("belay", belay);
  q.set("offset", String(offset));
  return request<GradeAscentsPage>("/statistics/grade-ascents?" + q, signal);
}
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
  version: number;
  physical_state?: string | null;
  local_date: string;
  status: string;
  environment: string;
  duration_minutes: number | null;
  notes: string | null;
  attempts: Attempt[];
  locations?: Place[];
  sectors?: string[];
  grades?: string[];
  demoLocation?: string;
  demoSector?: string;
};
export type User = { name: string; timezone: string; status: string };
export type Place = { id: string; name: string; region: string | null };
export type PlaceFilters = { regions: string[]; areas: Place[] };
export type Filters = {
  from: string;
  to: string;
  grade: string;
  region: string;
  areaId: string;
};
export class ApiError extends Error {
  constructor(public status: number) {
    super(
      status === 401
        ? "Войдите, чтобы увидеть свою статистику."
        : status === 403
          ? "Доступ к журналу пока не подтверждён."
          : status === 409
            ? "Тренировка уже изменена или завершена. Откройте форму заново."
            : status === 422
              ? "Проверьте заполненные поля и результат пролаза."
              : "Не удалось выполнить запрос. Попробуйте ещё раз.",
    );
  }
}
export async function request<T>(
  path: string,
  signal?: AbortSignal,
  mutation?: { csrf: string; method: "POST" | "PATCH"; body?: unknown; key?: string },
): Promise<T> {
  const r = await fetch("/api/v1" + path, {
    credentials: "include",
    signal,
    method: mutation?.method ?? "GET",
    headers: {
      Accept: "application/json",
      ...(mutation ? { "X-CSRF-Token": mutation.csrf } : {}),
      ...(mutation?.body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
      ...(mutation?.key ? { "Idempotency-Key": mutation.key } : {}),
    },
    body:
      mutation?.body !== undefined ? JSON.stringify(mutation.body) : undefined,
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

export async function editAttempt(
  trainingId: string, attemptId: string, body: Record<string, unknown>, csrf: string, key: string,
): Promise<Training> {
  await request(`/attempts/${encodeURIComponent(attemptId)}`, undefined, {
    method: "PATCH", csrf, body, key,
  });
  return request<Training>(`/trainings/${encodeURIComponent(trainingId)}`);
}

export async function activeTraining(
  signal?: AbortSignal,
): Promise<Training | null> {
  // Statistics intentionally hide empty/test-only sessions; controls must see them.
  let cursor: string | null = null;
  do {
    const page: { items: Training[]; next_cursor: string | null } =
      await request(
        "/trainings?include_test=true&limit=100" +
          (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
        signal,
      );
    const active = page.items.find((t) => t.status === "active");
    if (active) return active;
    cursor = page.next_cursor;
  } while (cursor);
  return null;
}
export function query(f: Filters) {
  const q = new URLSearchParams();
  if (f.from) q.set("date_from", f.from);
  if (f.to) q.set("date_to", f.to);
  if (f.grade) q.set("grade", f.grade);
  if (f.region) q.set("region", f.region);
  if (f.areaId) q.set("area_id", f.areaId);
  return q;
}
export async function dashboard(f: Filters, signal: AbortSignal) {
  const q = query(f);
  const [month, progress] = await Promise.all([
    request<Summary & { grades: Grade[] }>(
      `/statistics/${!f.from && !f.to ? "all" : "month"}?` + q, signal),
    request<{ periods: Period[] }>("/statistics/progress?" + q, signal),
  ]);
  return {
    summary: month,
    grades: month.grades ?? [],
    periods: progress.periods ?? [],
  };
}
export const trainingPage = (
  filters: Filters,
  cursor: string | null,
  signal: AbortSignal,
) =>
  request<{ items: Training[]; next_cursor: string | null }>(
    "/trainings?include_test=false&limit=12&" +
      query(filters) +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    signal,
  );

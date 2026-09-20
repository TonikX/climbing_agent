import type { JsonObject } from "./records.js";

const normalize = (value?: string) => value?.trim().toLowerCase();

function definedFields(value: JsonObject = {}) {
  return Object.fromEntries(Object.entries(value).filter(([, field]) => field !== undefined));
}

function attemptsCompatible(a: JsonObject, b: JsonObject) {
  if (a.routeId && b.routeId && a.routeId !== b.routeId) return false;
  const x = a.routeSnapshot ?? {};
  const y = b.routeSnapshot ?? {};
  for (const field of ["name", "grade", "sectorId", "areaId"]) {
    if (x[field] && y[field] && normalize(x[field]) !== normalize(y[field])) return false;
  }
  if (a.belay && b.belay && a.belay !== "unknown" && b.belay !== "unknown" && a.belay !== b.belay) return false;
  return Boolean((a.routeId && a.routeId === b.routeId) ||
    (x.name && normalize(x.name) === normalize(y.name)) ||
    (x.grade && normalize(x.grade) === normalize(y.grade)));
}

function mergeAttempt(
  existing: JsonObject,
  incoming: JsonObject,
) {
  return {
    ...existing,
    ...incoming,

    routeId:
      incoming.routeId ??
      existing.routeId,

    routeSnapshot: {
      ...(existing.routeSnapshot ?? {}),
      ...definedFields(incoming.routeSnapshot),
    },

    belay:
      incoming.belay &&
      incoming.belay !== "unknown"
        ? incoming.belay
        : existing.belay,

    attempts:
      incoming.attempts ??
      existing.attempts,

    result:
      incoming.result &&
      incoming.result !== "unknown"
        ? incoming.result
        : existing.result,

    style:
      incoming.style &&
      incoming.style !== "unknown"
        ? incoming.style
        : existing.style,

    feel:
      incoming.feel &&
      incoming.feel !== "unknown"
        ? incoming.feel
        : existing.feel,

    notes:
      incoming.notes ??
      existing.notes,
  };
}

export function mergeRouteAttempts(existing: JsonObject[], incoming: JsonObject[]) {
  const result = [...existing];
  // Match only against original events, never events just added by this summary.
  // Both sides must identify one unique candidate. Repeated/aggregate entries
  // remain separate rather than collapsing real events or guessing attribution.
  const candidates = incoming.map((entry) => existing.flatMap((old, index) =>
    attemptsCompatible(old, entry) ? [index] : []));
  incoming.forEach((entry, index) => {
    const matches = candidates[index];
    if (matches.length === 1 && candidates.filter((other) => other.includes(matches[0])).length === 1) {
      result[matches[0]] = mergeAttempt(existing[matches[0]], entry);
    } else {
      result.push(entry);
    }
  });
  return result;
}

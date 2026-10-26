import type { Grade, GradeAscentsPage, PyramidBucket } from "./api";
export const demoBuckets: Record<string, Record<PyramidBucket, number>> = {
  "7A": {
    onsight: 0,
    flash: 0,
    redpoint: 0,
    top_rope: 0,
    other_clean: 0,
    not_clean: 3,
  },
  "6C+": {
    onsight: 0,
    flash: 0,
    redpoint: 1,
    top_rope: 0,
    other_clean: 0,
    not_clean: 4,
  },
  "6C": {
    onsight: 0,
    flash: 1,
    redpoint: 2,
    top_rope: 0,
    other_clean: 0,
    not_clean: 5,
  },
  "6B+": {
    onsight: 1,
    flash: 2,
    redpoint: 3,
    top_rope: 0,
    other_clean: 0,
    not_clean: 4,
  },
  "6B": {
    onsight: 3,
    flash: 3,
    redpoint: 2,
    top_rope: 0,
    other_clean: 0,
    not_clean: 4,
  },
  "6A+": {
    onsight: 3,
    flash: 2,
    redpoint: 0,
    top_rope: 1,
    other_clean: 0,
    not_clean: 2,
  },
};
export function demoPyramidPage(
  grades: Grade[],
  grade: string,
  style: import("./api").AscentStyle | null,
  offset: number,
  belay?: string,
): GradeAscentsPage {
  const values = grades.find((g) => g.grade === grade)?.pyramid;
  const items: GradeAscentsPage["items"] = [];
  for (const [b, count] of Object.entries(values ?? {})) {
    for (let i = 0; i < count; i++) {
      const clean = b !== "not_clean";
      const attempt = {
        id: `${grade}-${b}-${i}`,
        sequence: 1,
        attempts: 1,
        reached_top: clean,
        clean_ascent: clean,
        style:
          b === "not_clean"
            ? i % 2
              ? "with_hangs"
              : "with_falls"
            : ["top_rope", "other_clean"].includes(b)
              ? "unknown"
              : b,
        belay: b === "top_rope" ? "top_rope" : "lead",
        falls: clean ? 0 : 1,
        hangs: 0,
        notes: null,
        is_test: false,
        route_snapshot: {
          name: ["Crying Boy", "Engesh", "Morning Light"][i % 3],
          grade,
        },
      };
      if (
        (style && attempt.style !== style) ||
        (belay && attempt.belay !== belay)
      )
        continue;
      items.push({
        trainingId: "demo-training",
        date: "2026-10-21",
        routeSessionKey: attempt.id,
        route: attempt.route_snapshot,
        location: { id: "demo-area", name: "Гейкбаири", region: "Анталья" },
        sector: { id: "demo-sector", name: "Мағара" },
        bucket: b as PyramidBucket,
        style: attempt.style,
        belay: attempt.belay,
        cleanAscent: clean,
        reachedTop: clean,
        attemptsCount: 1,
        attempts: [attempt],
      });
    }
  }
  return {
    items: items.slice(offset, offset + 20),
    total: items.length,
    nextOffset: offset + 20 < items.length ? offset + 20 : null,
  };
}

export function demoDimensions(g: Grade) {
  const entries = demoPyramidPage([g], g.grade, null, 0).items;
  const styles: Record<string, number> = {
    onsight: 0,
    flash: 0,
    redpoint: 0,
    with_falls: 0,
    with_hangs: 0,
    not_reached: 0,
    unknown: 0,
  };
  const belays: Record<string, number> = {
    lead: 0,
    top_rope: 0,
    auto_belay: 0,
    bouldering: 0,
    unknown: 0,
  };
  for (const item of entries) {
    styles[item.style]++;
    belays[item.belay]++;
  }
  return {
    styles: styles as Record<import("./api").AscentStyle, number>,
    belays,
  };
}

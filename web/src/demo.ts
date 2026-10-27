import { demoBuckets, demoDimensions } from "./pyramidDemo";
import type { Grade, Period, Summary, Training } from "./api";
// Isolated fixtures: never merged with API responses or sent to the backend.
export const summary: Summary = {
  ascentsCount: 53,
  ascentsByBelay: {
    lead: { total: 37, clean: 25, nonClean: 10, unknownClean: 2 },
    top_rope: { total: 16, clean: 7, nonClean: 8, unknownClean: 1 },
  },
  reachedByBelay: { lead: { total: 28, clean: 19, nonClean: 7, unknownClean: 2 }, top_rope: { total: 10, clean: 5, nonClean: 4, unknownClean: 1 } },
  trainingsCount: 8,
  routesCount: 46,
  attemptsCount: 78,
  reachedTopRoutes: 38,
  completedRoutes: 24,
  maxAttemptedGrade: "7A",
  maxReachedTopGrade: "6C+",
  maxCompletedGrade: "6C+",
};
const gradeValues: Grade[] = [
  { grade: "7A", routesCount: 3, attemptsCount: 9, completedRoutes: 0 },
  { grade: "6C+", routesCount: 5, attemptsCount: 12, completedRoutes: 1 },
  { grade: "6C", routesCount: 8, attemptsCount: 17, completedRoutes: 3 },
  { grade: "6B+", routesCount: 10, attemptsCount: 18, completedRoutes: 6 },
  { grade: "6B", routesCount: 12, attemptsCount: 14, completedRoutes: 8 },
  { grade: "6A+", routesCount: 8, attemptsCount: 8, completedRoutes: 6 },
];
export const grades: Grade[] = gradeValues.map((g) => ({
  ...g,
  pyramid: demoBuckets[g.grade],
  ...demoDimensions({ ...g, pyramid: demoBuckets[g.grade] }),
}));
export const periods: Period[] = [
  {
    period: "2026-10",
    attemptsCount: 78,
    completedRoutes: 24,
    maxCompletedGrade: "6C+",
  },
  {
    period: "2026-09",
    attemptsCount: 65,
    completedRoutes: 21,
    maxCompletedGrade: "6B",
  },
  {
    period: "2026-08",
    attemptsCount: 54,
    completedRoutes: 17,
    maxCompletedGrade: "6B",
  },
  {
    period: "2026-07",
    attemptsCount: 42,
    completedRoutes: 13,
    maxCompletedGrade: "6A+",
  },
  {
    period: "2026-06",
    attemptsCount: 38,
    completedRoutes: 10,
    maxCompletedGrade: "6A",
  },
  {
    period: "2026-05",
    attemptsCount: 28,
    completedRoutes: 8,
    maxCompletedGrade: "6A",
  },
];
export const trainings: Training[] = [
  "2026-10-21",
  "2026-10-18",
  "2026-10-15",
].map((date, i) => ({
  id: "demo-" + i,
  version: 1,
  local_date: date,
  status: i === 0 ? "active" : "completed",
  environment: "outdoor",
  duration_minutes: 110 + i * 20,
  notes: null,
  demoLocation: "Гейкбаири",
  demoSector: ["Мағара", "Кебап", "Требенна"][i],
  locations: [{ id: "demo-geyikbayiri", name: "Гейкбаири", region: "Анталья" }],
  sectors: [["Мағара", "Кебап", "Требенна"][i]],
  grades: ["6A+", "6B+"],
  attempts: [
    {
      id: "a" + i,
      sequence: 1,
      attempts: 2,
      reached_top: true,
      clean_ascent: false,
      style: "hang",
      belay: "lead",
      falls: 0,
      hangs: 1,
      notes: "Работа над ключом в середине трассы.",
      is_test: false,
      route_snapshot: {
        name: ["Crying Boy", "Engesh", "Revolverheld"][i],
        grade: "6B+",
      },
    },
    {
      id: "b" + i,
      sequence: 2,
      attempts: 1,
      reached_top: true,
      clean_ascent: true,
      style: "flash",
      belay: "lead",
      falls: 0,
      hangs: 0,
      notes: null,
      is_test: false,
      route_snapshot: { name: "Morning Light", grade: "6A+" },
    },
  ],
}));

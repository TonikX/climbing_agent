import { randomUUID } from "node:crypto";
import { Type, type Static, type TSchema } from "typebox";
import type { JsonObject } from "../domain/records.js";
import { mergeRouteAttempts } from "../domain/merge-attempts.js";
import { collections as FILES, type JournalStore } from "../storage/store.js";

function defineOperation<S extends TSchema, R>(definition: {
  name: string;
  label: string;
  description: string;
  parameters: S;
  execute(input: Static<S>): Promise<R>;
}) { return definition; }

// Operations have no dependency on OpenClaw or filesystem paths. The transport
// validates input against parameters; future HTTP auth must resolve the user.
export function createJournalService(store: JournalStore) {
  const readArray = store.read.bind(store);
  const writeArray = store.write.bind(store);
  const withStorage = store.transaction.bind(store);
function normalize(value?: string) {
  return value?.trim().toLowerCase();
}

function now() {
  return new Date().toISOString();
}

function newId(prefix: string) {
  return `${prefix}_${randomUUID()}`;
}

function refsIntersect(
  a: JsonObject[] = [],
  b: JsonObject[] = [],
) {
  return a.some((x) =>
    b.some(
      (y) =>
        x.system === y.system &&
        x.id &&
        y.id &&
        x.id === y.id,
    ),
  );
}

function mergeRefs(
  current: JsonObject[] = [],
  incoming: JsonObject[] = [],
) {
  const result = [...current];

  for (const ref of incoming) {
    const exists = result.some(
      (existing) =>
        existing.system === ref.system &&
        (
          (existing.id && ref.id && existing.id === ref.id) ||
          (existing.url && ref.url && existing.url === ref.url)
        ),
    );

    if (!exists) {
      result.push(ref);
    }
  }

  return result;
}

const ExternalRefSchema = Type.Object(
  {
    system: Type.String(),
    id: Type.Optional(Type.String()),
    url: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);

const UserDescriptorSchema = Type.Object(
  {
    id: Type.Optional(Type.String()),
    name: Type.Optional(Type.String()),
    externalRefs: Type.Optional(Type.Array(ExternalRefSchema)),
  },
  { additionalProperties: false },
);

const AreaDescriptorSchema = Type.Object(
  {
    id: Type.Optional(Type.String()),
    name: Type.Optional(Type.String()),
    country: Type.Optional(Type.String()),
    latitude: Type.Optional(Type.Number()),
    longitude: Type.Optional(Type.Number()),
    externalRefs: Type.Optional(Type.Array(ExternalRefSchema)),
  },
  { additionalProperties: false },
);

const SectorDescriptorSchema = Type.Object(
  {
    id: Type.Optional(Type.String()),
    name: Type.Optional(Type.String()),
    externalRefs: Type.Optional(Type.Array(ExternalRefSchema)),
  },
  { additionalProperties: false },
);

const WeatherSchema = Type.Object(
  {
    temperatureC: Type.Optional(Type.Number()),
    conditions: Type.Optional(Type.String()),
    wind: Type.Optional(Type.String()),
    humidity: Type.Optional(Type.String()),
    rockCondition: Type.Optional(Type.String()),
    notes: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);

const GearSchema = Type.Object(
  {
    id: Type.Optional(Type.String()),

    type: Type.Union([
      Type.Literal("shoes"),
      Type.Literal("rope"),
      Type.Literal("harness"),
      Type.Literal("belay_device"),
      Type.Literal("helmet"),
      Type.Literal("chalk"),
      Type.Literal("other"),
    ]),

    brand: Type.Optional(Type.String()),
    model: Type.Optional(Type.String()),
    size: Type.Optional(Type.String()),
    nickname: Type.Optional(Type.String()),
    active: Type.Optional(Type.Boolean()),
    notes: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);

const RouteAttemptSchema = Type.Object(
  {
    routeId: Type.Optional(Type.String()),

    name: Type.Optional(Type.String()),
    grade: Type.Optional(Type.String()),

    sector: Type.Optional(SectorDescriptorSchema),

    externalRefs: Type.Optional(Type.Array(ExternalRefSchema)),

    belay: Type.Optional(
      Type.Union([
        Type.Literal("lead"),
        Type.Literal("top_rope"),
        Type.Literal("auto_belay"),
        Type.Literal("bouldering"),
        Type.Literal("unknown"),
      ]),
    ),

    attempts: Type.Optional(
      Type.Integer({ minimum: 1 }),
    ),

    result: Type.Optional(
      Type.Union([
        Type.Literal("send"),
        Type.Literal("project"),
        Type.Literal("attempted"),
        Type.Literal("unknown"),
      ]),
    ),

    style: Type.Optional(
      Type.Union([
        Type.Literal("onsight"),
        Type.Literal("flash"),
        Type.Literal("redpoint"),
        Type.Literal("unknown"),
      ]),
    ),

    feel: Type.Optional(
      Type.Union([
        Type.Literal("easy"),
        Type.Literal("comfortable"),
        Type.Literal("limit"),
        Type.Literal("unknown"),
      ]),
    ),

    notes: Type.Optional(Type.String()),

    isTest: Type.Optional(
      Type.Boolean({
        description:
          "True when the attempt was created only to test the bot and must be excluded from statistics.",
      }),
    ),
  },
  { additionalProperties: false },
);

type UserDescriptor = Static<typeof UserDescriptorSchema>;
type AttemptInput = Static<typeof RouteAttemptSchema>;
type GearInput = Static<typeof GearSchema>;

function getUserByDescriptor(input: UserDescriptor) {
  const users = readArray(FILES.users);
  const matches = users.filter((user) => refsIntersect(user.externalRefs, input.externalRefs));
  if (matches.length > 1) throw new Error("External references identify different users");
  if (input.id) {
    const user = users.find((x) => x.id === input.id);
    if (!user) throw new Error(`User ${input.id} does not exist`);
    if (matches.some((x) => x.id !== user.id)) throw new Error("Conflicting user identity");
    for (const ref of input.externalRefs ?? []) {
      if (ref.id && (user.externalRefs ?? []).some((x: JsonObject) =>
        x.system === ref.system && x.id && x.id !== ref.id)) {
        throw new Error("Conflicting external user identity");
      }
    }
    return user;
  }
  if ((input.externalRefs ?? []).some((ref) => ref.id)) {
    const matched = matches[0];
    for (const ref of input.externalRefs ?? []) {
      if (matched && ref.id && (matched.externalRefs ?? []).some((x: JsonObject) =>
        x.system === ref.system && x.id && x.id !== ref.id)) {
        throw new Error("Conflicting external user identity");
      }
    }
    return matched;
  }
  const named = users.filter((x) => normalize(x.name) === normalize(input.name) && normalize(input.name));
  if (named.length > 1) throw new Error("Ambiguous user name; supply an ID or external reference");
  return named[0];
}

function ensureUser(input: UserDescriptor) {
  const user = getUserByDescriptor(input);
  const users = readArray(FILES.users);
  if (user) {
    user.externalRefs = mergeRefs(user.externalRefs, input.externalRefs);
    users[users.findIndex((x) => x.id === user.id)] = user;
    writeArray(FILES.users, users);
    return user;
  }
  if (!normalize(input.name)) throw new Error("Cannot create a new user without a name");
  const created = { id: newId("user"), name: input.name, externalRefs: input.externalRefs ?? [], createdAt: now() };
  users.push(created);
  writeArray(FILES.users, users);
  return created;
}

function validateGearIds(userId: string, ids: string[] = []) {
  const gear = readArray(FILES.gear);
  for (const id of ids) {
    if (!gear.some((item) => item.id === id && item.userId === userId)) {
      throw new Error(`Gear ${id} does not belong to this user`);
    }
  }
}

function ensureArea(input?: JsonObject) {
  if (!input) {
    return undefined;
  }

  const areas = readArray(FILES.areas);
  if (input.id && !areas.some((x) => x.id === input.id)) throw new Error("Unknown area ID");
  const namedAreas = input.name ? areas.filter((x) =>
    normalize(x.name) === normalize(input.name) &&
    (!input.country || !x.country || normalize(x.country) === normalize(input.country))) : [];
  if (!input.id && !areas.some((x) => refsIntersect(x.externalRefs, input.externalRefs)) && namedAreas.length > 1) {
    throw new Error("Ambiguous area name; supply an ID or country");
  }

  let area =
    (input.id
      ? areas.find((x) => x.id === input.id)
      : undefined) ??
    areas.find((x) =>
      refsIntersect(x.externalRefs, input.externalRefs),
    ) ??
    namedAreas[0];

  if (area) {
    if (!area.country && input.country) area.country = input.country;
    area.externalRefs = mergeRefs(
      area.externalRefs,
      input.externalRefs,
    );

    if (area.latitude == null && input.latitude != null) {
      area.latitude = input.latitude;
    }

    if (area.longitude == null && input.longitude != null) {
      area.longitude = input.longitude;
    }

    writeArray(FILES.areas, areas);

    return area;
  }

  if (!input.name) {
    throw new Error(
      "Cannot create an area without a name.",
    );
  }

  area = {
    id: newId("area"),
    name: input.name,
    country: input.country,
    latitude: input.latitude,
    longitude: input.longitude,
    externalRefs: input.externalRefs ?? [],
    createdAt: now(),
  };

  areas.push(area);

  writeArray(FILES.areas, areas);

  return area;
}

function ensureSector(
  areaId: string | undefined,
  input?: JsonObject,
) {
  if (!input) {
    return undefined;
  }

  const sectors = readArray(FILES.sectors);
  if (input.id && !sectors.some((x) => x.id === input.id)) throw new Error("Unknown sector ID");

  let sector =
    (input.id
      ? sectors.find((x) => x.id === input.id)
      : undefined) ??
    sectors.find((x) =>
      refsIntersect(x.externalRefs, input.externalRefs),
    ) ??
    (input.name
      ? sectors.find(
          (x) =>
            x.areaId === areaId &&
            normalize(x.name) === normalize(input.name),
        )
      : undefined);

  if (sector) {
    if (areaId && sector.areaId !== areaId) throw new Error("Sector does not belong to the selected area");
    sector.externalRefs = mergeRefs(
      sector.externalRefs,
      input.externalRefs,
    );

    writeArray(FILES.sectors, sectors);

    return sector;
  }

  if (!input.name) {
    throw new Error(
      "Cannot create a sector without a name.",
    );
  }

  if (!areaId) throw new Error("An area is required to create a sector");

  sector = {
    id: newId("sector"),
    areaId,
    name: input.name,
    externalRefs: input.externalRefs ?? [],
    createdAt: now(),
  };

  sectors.push(sector);

  writeArray(FILES.sectors, sectors);

  return sector;
}

function ensureRoute(
  sectorId: string | undefined,
  input: JsonObject,
) {
  const routes = readArray(FILES.routes);

  if (input.routeId) {
    const existing = routes.find(
      (x) => x.id === input.routeId,
    );

    if (!existing) {
      throw new Error(
        `Route ${input.routeId} does not exist.`,
      );
    }

    if (sectorId && existing.sectorId !== sectorId) throw new Error("Route does not belong to the selected sector");
    return existing;
  }

  /*
   * If the route has no name, don't create a catalogue entity.
   * We still keep a routeSnapshot inside the training.
   */
  if (!normalize(input.name) || !sectorId) {
    return undefined;
  }

  let route =
    routes.find((x) =>
      refsIntersect(x.externalRefs, input.externalRefs),
    ) ??
    routes.find(
      (x) =>
        x.sectorId === sectorId &&
        normalize(x.name) === normalize(input.name),
    );

  if (route) {
    if (route.sectorId !== sectorId) throw new Error("Route does not belong to the selected sector");
    route.externalRefs = mergeRefs(
      route.externalRefs,
      input.externalRefs,
    );

    /*
     * Fill a missing grade, but never silently overwrite one.
     */
    if (!route.grade && input.grade) {
      route.grade = input.grade;
    }

    writeArray(FILES.routes, routes);

    return route;
  }

  route = {
    id: newId("route"),
    sectorId,
    name: input.name,
    grade: input.grade,
    externalRefs: input.externalRefs ?? [],
    createdAt: now(),
  };

  routes.push(route);

  writeArray(FILES.routes, routes);

  return route;
}

function upsertGear(
  userId: string,
  input: GearInput,
) {
  const gear = readArray(FILES.gear);
  if (input.id && !gear.some((x) => x.id === input.id && x.userId === userId)) throw new Error("Unknown gear ID for this user");

  let item =
    (input.id
      ? gear.find(
          (x) =>
            x.id === input.id &&
            x.userId === userId,
        )
      : undefined) ??
    gear.find(
      (x) =>
        x.userId === userId &&
        x.type === input.type &&
        normalize(x.brand) === normalize(input.brand) &&
        normalize(x.model) === normalize(input.model) &&
        normalize(x.size) === normalize(input.size),
    );

  if (item) {
    Object.assign(item, {
      ...input,
      id: item.id,
      userId,
      updatedAt: now(),
    });

    writeArray(FILES.gear, gear);

    return item;
  }

  item = {
    ...input,
    id: newId("gear"),
    userId,
    active: input.active ?? true,
    createdAt: now(),
  };

  gear.push(item);

  writeArray(FILES.gear, gear);

  return item;
}

function getActiveTraining(userId: string) {
  const trainings = readArray(FILES.trainings);

  return trainings
    .filter(
      (x) =>
        x.userId === userId &&
        x.status === "active",
    )
    .sort((a, b) =>
      String(b.createdAt).localeCompare(
        String(a.createdAt),
      ),
    )[0];
}

function updateTrainingRecord(
  trainingId: string,
  updater: (training: JsonObject) => void,
) {
  const trainings = readArray(FILES.trainings);

  const training = trainings.find(
    (x) => x.id === trainingId,
  );

  if (!training) {
    throw new Error(
      `Training ${trainingId} does not exist.`,
    );
  }

  updater(training);

  training.updatedAt = now();

  writeArray(FILES.trainings, trainings);

  return training;
}

function resolveAttempt(
  area: JsonObject | undefined,
  defaultSector: JsonObject | undefined,
  attempt: AttemptInput,
) {
  const sector = attempt.sector
    ? ensureSector(
        area?.id,
        attempt.sector,
      )
    : defaultSector;

  const route = ensureRoute(
    sector?.id,
    attempt,
  );

  const routeSector = route?.sectorId
    ? readArray(FILES.sectors).find((x) => x.id === route.sectorId)
    : undefined;
  if (area?.id && routeSector?.areaId && area.id !== routeSector.areaId) {
    throw new Error("Route does not belong to the selected area");
  }
  return {
    routeId: route?.id,

    routeSnapshot: {
      name:
        attempt.name ??
        route?.name,

      grade:
        attempt.grade ??
        route?.grade,

      areaId:
        area?.id ?? routeSector?.areaId,

      sectorId:
        sector?.id ?? routeSector?.id,
    },

    belay:
      attempt.belay ??
      "unknown",

    attempts:
      attempt.attempts,

    result:
      attempt.result ??
      "unknown",

    style:
      attempt.style ??
      "unknown",

    feel:
      attempt.feel ??
      "unknown",

    notes:
      attempt.notes,

    isTest:
      attempt.isTest,
  };
}


  return {
    start_climbing_training: defineOperation({
      name: "start_climbing_training",

      label: "Start climbing training",

      description:
        "Start a new active climbing training session. If another active session exists for the same user, close it first.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          date:
            Type.String(),

          startedAt:
            Type.Optional(
              Type.String(),
            ),

          environment:
            Type.Optional(
              Type.Union([
                Type.Literal("indoor"),
                Type.Literal("outdoor"),
                Type.Literal("unknown"),
              ]),
            ),

          area:
            Type.Optional(
              AreaDescriptorSchema,
            ),

          sector:
            Type.Optional(
              SectorDescriptorSchema,
            ),

          weather:
            Type.Optional(
              WeatherSchema,
            ),

          gearIds:
            Type.Optional(
              Type.Array(
                Type.String(),
              ),
            ),

          notes:
            Type.Optional(
              Type.String(),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(input) {
        return withStorage(() => {
        const user =
          ensureUser(input.user);
        validateGearIds(user.id, input.gearIds);

        const trainings =
          readArray(FILES.trainings);

        for (const training of trainings) {
          if (
            training.userId === user.id &&
            training.status === "active"
          ) {
            training.status =
              "completed";

            training.completedAt =
              now();

            training.updatedAt =
              now();
          }
        }

        const area =
          ensureArea(input.area);

        const sector =
          ensureSector(
            area?.id,
            input.sector,
          );

        const record = {
          id:
            newId("training"),

          userId:
            user.id,

          status:
            "active",

          createdAt:
            now(),

          date:
            input.date,

          startedAt:
            input.startedAt,

          environment:
            input.environment ??
            "unknown",

          areaId:
            area?.id,

          sectorIds:
            sector
              ? [sector.id]
              : [],

          weather:
            input.weather,

          gearIds:
            input.gearIds ??
            [],

          routes: [],

          notes:
            input.notes,
        };

        trainings.push(record);

        writeArray(
          FILES.trainings,
          trainings,
        );

        return {
          success: true,
          trainingId: record.id,
          status: "active",
        };
        });
      },
    }),

    append_climbing_attempt: defineOperation({
      name: "append_climbing_attempt",

      label: "Append climbing attempt",

      description:
        "Append one newly reported route attempt or ascent to the user's active training. If there is no active training, create one.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          date:
            Type.String(),

          area:
            Type.Optional(
              AreaDescriptorSchema,
            ),

          sector:
            Type.Optional(
              SectorDescriptorSchema,
            ),

          attempt:
            RouteAttemptSchema,
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(input) {
        return withStorage(() => {
        const user =
          ensureUser(input.user);

        let active =
          getActiveTraining(user.id);

        if (active && active.date !== input.date) throw new Error("Active training has a different date; finish it or explicitly start a new training");
        const providedArea =
          ensureArea(input.area);

        let providedSector =
          ensureSector(
            providedArea?.id ?? active?.areaId,
            input.sector,
          );

        if (!active) {
          const trainings =
            readArray(
              FILES.trainings,
            );

          active = {
            id:
              newId("training"),

            userId:
              user.id,

            status:
              "active",

            createdAt:
              now(),

            date:
              input.date,

            environment:
              "unknown",

            areaId:
              providedArea?.id,

            sectorIds:
              providedSector
                ? [
                    providedSector.id,
                  ]
                : [],

            gearIds: [],

            routes: [],
          };

          trainings.push(active);

          writeArray(
            FILES.trainings,
            trainings,
          );
        }

        let effectiveArea =
          providedArea;

        if (
          !effectiveArea &&
          active.areaId
        ) {
          effectiveArea =
            readArray(
              FILES.areas,
            ).find(
              (x) =>
                x.id ===
                active.areaId,
            );
        }

        if (
          !providedSector &&
          (!providedArea || providedArea.id === active.areaId) &&
          active.sectorIds?.length
        ) {
          providedSector =
            readArray(
              FILES.sectors,
            ).find(
              (x) =>
                x.id ===
                active.sectorIds[
                  active.sectorIds.length - 1
                ],
            );
        }

        const resolved =
          resolveAttempt(
            effectiveArea,
            providedSector,
            input.attempt,
          );

        const updated =
          updateTrainingRecord(
            active.id,
            (record) => {
              record.routes ??= [];

              /*
               * Intentional append.
               * Two messages about the same route may represent
               * two genuinely separate attempts.
               */
              record.routes.push(
                resolved,
              );

              if (
                effectiveArea?.id &&
                !record.areaId
              ) {
                record.areaId =
                  effectiveArea.id;
              }

              const sectorId =
                resolved
                  .routeSnapshot
                  ?.sectorId;

              if (sectorId) {
                record.sectorIds ??= [];

                if (
                  !record.sectorIds.includes(
                    sectorId,
                  )
                ) {
                  record.sectorIds.push(
                    sectorId,
                  );
                }
              }
            },
          );

        return {
          success: true,

          trainingId:
            updated.id,

          status:
            updated.status,

          loggedEvents:
            updated.routes?.length ??
            0,
        };
        });
      },
    }),

    save_climbing_training: defineOperation({
      name: "save_climbing_training",

      label: "Save climbing training",

      description:
        "Save a complete training or merge a final summary into the user's currently active training.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          date:
            Type.String(),

          startedAt:
            Type.Optional(
              Type.String(),
            ),

          durationMinutes:
            Type.Optional(
              Type.Number({
                minimum: 1,
              }),
            ),

          environment:
            Type.Optional(
              Type.Union([
                Type.Literal("indoor"),
                Type.Literal("outdoor"),
                Type.Literal("unknown"),
              ]),
            ),

          area:
            Type.Optional(
              AreaDescriptorSchema,
            ),

          sector:
            Type.Optional(
              SectorDescriptorSchema,
            ),

          weather:
            Type.Optional(
              WeatherSchema,
            ),

          gearIds:
            Type.Optional(
              Type.Array(
                Type.String(),
              ),
            ),

          routes:
            Type.Optional(
              Type.Array(
                RouteAttemptSchema,
              ),
            ),

          physicalState:
            Type.Optional(
              Type.String(),
            ),

          notes:
            Type.Optional(
              Type.String(),
            ),

          mergeIntoActive:
            Type.Optional(
              Type.Boolean(),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(input) {
        return withStorage(() => {
        const user =
          ensureUser(input.user);
        validateGearIds(user.id, input.gearIds);

        let area =
          ensureArea(input.area);

        const active = input.mergeIntoActive ? getActiveTraining(user.id) : undefined;
        if (active && active.date !== input.date) throw new Error("Summary date differs from active training date");

        if (
          !area &&
          active?.areaId
        ) {
          area =
            readArray(
              FILES.areas,
            ).find(
              (x) =>
                x.id ===
                active.areaId,
            );
        }

        let defaultSector =
          ensureSector(
            area?.id,
            input.sector,
          );

        if (
          !defaultSector &&
          (!area || area.id === active?.areaId) &&
          active?.sectorIds?.length
        ) {
          defaultSector =
            readArray(
              FILES.sectors,
            ).find(
              (x) =>
                x.id ===
                active.sectorIds[
                  active.sectorIds.length - 1
                ],
            );
        }

        const incomingAttempts =
          (input.routes ?? []).map(
            (attempt) =>
              resolveAttempt(
                area,
                defaultSector,
                attempt,
              ),
          );

        if (
          input.mergeIntoActive &&
          active
        ) {
          const updated =
            updateTrainingRecord(
              active.id,
              (record) => {
                record.routes =
                  mergeRouteAttempts(
                    record.routes ??
                      [],
                    incomingAttempts,
                  );

                if (
                  input.durationMinutes != null
                ) {
                  record.durationMinutes =
                    input.durationMinutes;
                }

                if (
                  input.startedAt
                ) {
                  record.startedAt =
                    input.startedAt;
                }

                if (
                  input.environment &&
                  input.environment !==
                    "unknown"
                ) {
                  record.environment =
                    input.environment;
                }

                if (
                  area?.id
                ) {
                  record.areaId =
                    area.id;
                }

                if (
                  input.weather
                ) {
                  record.weather = {
                    ...(record.weather ?? {}),
                    ...input.weather,
                  };
                }

                if (
                  input.gearIds
                ) {
                  record.gearIds = [
                    ...new Set([
                      ...(record.gearIds ?? []),
                      ...input.gearIds,
                    ]),
                  ];
                }

                if (
                  input.physicalState
                ) {
                  record.physicalState =
                    input.physicalState;
                }

                if (
                  input.notes
                ) {
                  record.notes =
                    input.notes;
                }

                record.sectorIds = [...new Set([
                  ...(record.sectorIds ?? []),
                  ...(defaultSector ? [defaultSector.id] : []),
                  ...new Set(
                    (
                      record.routes ??
                      []
                    )
                      .map(
                        (
                          x: JsonObject,
                        ) =>
                          x
                            .routeSnapshot
                            ?.sectorId,
                      )
                      .filter(Boolean),
                  ),
                ])];
              },
            );

          return {
            success: true,
            merged: true,

            trainingId:
              updated.id,

            routeCount:
              updated.routes?.length ??
              0,
          };
        }

        const trainings =
          readArray(
            FILES.trainings,
          );

        const record = {
          id:
            newId("training"),

          userId:
            user.id,

          status:
            "completed",

          createdAt:
            now(),

          completedAt:
            now(),

          date:
            input.date,

          startedAt:
            input.startedAt,

          durationMinutes:
            input.durationMinutes,

          environment:
            input.environment ??
            "unknown",

          areaId:
            area?.id,

          sectorIds: [...new Set([
            ...(defaultSector ? [defaultSector.id] : []),
            ...new Set(
              incomingAttempts
                .map(
                  (x) =>
                    x
                      .routeSnapshot
                      ?.sectorId,
                )
                .filter(Boolean),
            ),
          ])],

          weather:
            input.weather,

          gearIds:
            input.gearIds ??
            [],

          routes:
            incomingAttempts,

          physicalState:
            input.physicalState,

          notes:
            input.notes,
        };

        trainings.push(record);

        writeArray(
          FILES.trainings,
          trainings,
        );

        return {
          success: true,
          merged: false,

          trainingId:
            record.id,

          routeCount:
            incomingAttempts.length,
        };
        });
      },
    }),

    update_climbing_training: defineOperation({
      name: "update_climbing_training",

      label: "Update climbing training",

      description:
        "Update training metadata such as duration, location, weather, gear, physical condition or notes.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          trainingId:
            Type.Optional(
              Type.String(),
            ),

          durationMinutes:
            Type.Optional(
              Type.Number({
                minimum: 1,
              }),
            ),

          environment:
            Type.Optional(
              Type.Union([
                Type.Literal("indoor"),
                Type.Literal("outdoor"),
                Type.Literal("unknown"),
              ]),
            ),

          area:
            Type.Optional(
              AreaDescriptorSchema,
            ),

          sector:
            Type.Optional(
              SectorDescriptorSchema,
            ),

          weather:
            Type.Optional(
              WeatherSchema,
            ),

          gearIds:
            Type.Optional(
              Type.Array(
                Type.String(),
              ),
            ),

          physicalState:
            Type.Optional(
              Type.String(),
            ),

          notes:
            Type.Optional(
              Type.String(),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(input) {
        return withStorage(() => {
        const user =
          ensureUser(input.user);
        validateGearIds(user.id, input.gearIds);

        let training: JsonObject | undefined;

        if (
          input.trainingId
        ) {
          training =
            readArray(
              FILES.trainings,
            ).find(
              (x) =>
                x.id ===
                  input.trainingId &&
                x.userId ===
                  user.id,
            );
        } else {
          training =
            getActiveTraining(
              user.id,
            );
        }

        if (!training) {
          throw new Error(
            "No matching climbing training found.",
          );
        }

        const area =
          ensureArea(
            input.area,
          );

        const sector =
          ensureSector(
            area?.id ??
              training.areaId,
            input.sector,
          );

        const updated =
          updateTrainingRecord(
            training.id,
            (record) => {
              if (
                input.durationMinutes != null
              ) {
                record.durationMinutes =
                  input.durationMinutes;
              }

              if (
                input.environment
              ) {
                record.environment =
                  input.environment;
              }

              if (
                area?.id
              ) {
                record.areaId =
                  area.id;
              }

              if (
                sector?.id
              ) {
                record.sectorIds ??= [];

                if (
                  !record.sectorIds.includes(
                    sector.id,
                  )
                ) {
                  record.sectorIds.push(
                    sector.id,
                  );
                }
              }

              if (
                input.weather
              ) {
                record.weather = {
                  ...(record.weather ?? {}),
                  ...input.weather,
                };
              }

              if (
                input.gearIds
              ) {
                record.gearIds = [
                  ...new Set([
                    ...(record.gearIds ?? []),
                    ...input.gearIds,
                  ]),
                ];
              }

              if (
                input.physicalState
              ) {
                record.physicalState =
                  input.physicalState;
              }

              if (
                input.notes
              ) {
                record.notes =
                  input.notes;
              }
            },
          );

        return {
          success: true,
          trainingId:
            updated.id,
        };
        });
      },
    }),

    finish_climbing_training: defineOperation({
      name: "finish_climbing_training",

      label: "Finish climbing training",

      description:
        "Finish the user's currently active climbing training.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          durationMinutes:
            Type.Optional(
              Type.Number({
                minimum: 1,
              }),
            ),

          physicalState:
            Type.Optional(
              Type.String(),
            ),

          notes:
            Type.Optional(
              Type.String(),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(input) {
        return withStorage(() => {
        const user =
          ensureUser(input.user);

        const active =
          getActiveTraining(
            user.id,
          );

        if (!active) {
          throw new Error(
            "No active climbing training found.",
          );
        }

        const updated =
          updateTrainingRecord(
            active.id,
            (record) => {
              record.status =
                "completed";

              record.completedAt =
                now();

              if (
                input.durationMinutes != null
              ) {
                record.durationMinutes =
                  input.durationMinutes;
              }

              if (
                input.physicalState
              ) {
                record.physicalState =
                  input.physicalState;
              }

              if (
                input.notes
              ) {
                record.notes =
                  input.notes;
              }
            },
          );

        return {
          success: true,

          trainingId:
            updated.id,

          status:
            "completed",

          routeCount:
            updated.routes?.length ??
            0,
        };
        });
      },
    }),

    upsert_climbing_gear: defineOperation({
      name: "upsert_climbing_gear",

      label: "Add or update climbing gear",

      description:
        "Create or update persistent climbing equipment belonging to a user.",

      parameters: Type.Object(
        {
          user:
            UserDescriptorSchema,

          gear:
            GearSchema,
        },
        {
          additionalProperties: false,
        },
      ),

      async execute({
        user: userInput,
        gear,
      }) {
        return withStorage(() => {
        const user =
          ensureUser(
            userInput,
          );

        const item =
          upsertGear(
            user.id,
            gear,
          );

        return {
          success: true,
          gear: item,
        };
        });
      },
    }),

    find_climbing_routes: defineOperation({
      name: "find_climbing_routes",

      label: "Find climbing routes",

      description:
        "Search the local climbing route catalogue by area, sector, route name or grade.",

      parameters: Type.Object(
        {
          area:
            Type.Optional(
              Type.String(),
            ),

          sector:
            Type.Optional(
              Type.String(),
            ),

          name:
            Type.Optional(
              Type.String(),
            ),

          grade:
            Type.Optional(
              Type.String(),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(query) {
        return withStorage(() => {
        const areas =
          readArray(
            FILES.areas,
          );

        const sectors =
          readArray(
            FILES.sectors,
          );

        const routes =
          readArray(
            FILES.routes,
          );

        const result: JsonObject[] =
          routes
            .map(
              (
                route,
              ): JsonObject => {
                const sector =
                  sectors.find(
                    (x) =>
                      x.id ===
                      route.sectorId,
                  );

                const area =
                  areas.find(
                    (x) =>
                      x.id ===
                      sector?.areaId,
                  );

                return {
                  ...route,
                  sector,
                  area,
                };
              },
            )
            .filter(
              (
                item: JsonObject,
              ) => {
                if (
                  query.name &&
                  !normalize(
                    item.name,
                  )?.includes(
                    normalize(
                      query.name,
                    )!,
                  )
                ) {
                  return false;
                }

                if (
                  query.grade &&
                  normalize(
                    item.grade,
                  ) !==
                    normalize(
                      query.grade,
                    )
                ) {
                  return false;
                }

                if (
                  query.sector &&
                  !normalize(
                    item.sector?.name,
                  )?.includes(
                    normalize(
                      query.sector,
                    )!,
                  )
                ) {
                  return false;
                }

                if (
                  query.area &&
                  !normalize(
                    item.area?.name,
                  )?.includes(
                    normalize(
                      query.area,
                    )!,
                  )
                ) {
                  return false;
                }

                return true;
              },
            );

        return {
          count:
            result.length,

          routes:
            result,
        };
        });
      },
    }),

    get_climbing_trainings: defineOperation({
      name: "get_climbing_trainings",

      label: "Get climbing trainings",

      description:
        "Read climbing trainings with resolved user, area, sector, route and gear information.",

      parameters: Type.Object(
        {
          userId:
            Type.Optional(
              Type.String(),
            ),

          userName:
            Type.Optional(
              Type.String(),
            ),

          status:
            Type.Optional(
              Type.Union([
                Type.Literal("active"),
                Type.Literal("completed"),
              ]),
            ),

          dateFrom:
            Type.Optional(
              Type.String(),
            ),

          dateTo:
            Type.Optional(
              Type.String(),
            ),

          area:
            Type.Optional(
              Type.String(),
            ),

          sector:
            Type.Optional(
              Type.String(),
            ),

          route:
            Type.Optional(
              Type.String(),
            ),

          grade:
            Type.Optional(
              Type.String(),
            ),

          limit:
            Type.Optional(
              Type.Integer({
                minimum: 1,
                maximum: 500,
              }),
            ),

          includeTest:
            Type.Optional(
              Type.Boolean({
                description:
                  "Include bot-test attempts. Leave false for history and statistics unless the user explicitly asks for test records.",
              }),
            ),
        },
        {
          additionalProperties: false,
        },
      ),

      async execute(query) {
        return withStorage(() => {
        const users =
          readArray(
            FILES.users,
          );

        const areas =
          readArray(
            FILES.areas,
          );

        const sectors =
          readArray(
            FILES.sectors,
          );

        const routes =
          readArray(
            FILES.routes,
          );

        const gear =
          readArray(
            FILES.gear,
          );

        let userId =
          query.userId;

        if (!userId && query.userName) {
          userId = getUserByDescriptor({ name: query.userName })?.id;
          if (!userId) return { count: 0, trainings: [] };
        }

        let trainings =
          readArray(
            FILES.trainings,
          );

        trainings =
          trainings.filter(
            (training) => {
              const visibleAttempts =
                (training.routes ?? []).filter(
                  (attempt: JsonObject) =>
                    query.includeTest ||
                    attempt.isTest !== true,
                );

              if (
                userId &&
                training.userId !==
                  userId
              ) {
                return false;
              }

              if (
                query.status &&
                training.status !==
                  query.status
              ) {
                return false;
              }

              if (
                query.dateFrom &&
                training.date <
                  query.dateFrom
              ) {
                return false;
              }

              if (
                query.dateTo &&
                training.date >
                  query.dateTo
              ) {
                return false;
              }

              const area =
                areas.find(
                  (x) =>
                    x.id ===
                    training.areaId,
                );

              if (
                query.area &&
                !normalize(
                  area?.name,
                )?.includes(
                  normalize(
                    query.area,
                  )!,
                )
              ) {
                return false;
              }

              if (query.sector && !query.route && !query.grade && !(training.sectorIds ?? []).some((id: string) =>
                sectors.some((sector) => sector.id === id && normalize(sector.name)?.includes(normalize(query.sector)!)))) {
                return false;
              }

              if (
                query.route ||
                query.grade
              ) {
                const routeMatch =
                  (
                    visibleAttempts
                  ).some(
                    (
                      attempt: JsonObject,
                    ) => {
                      const route =
                        routes.find(
                          (x) =>
                            x.id ===
                            attempt.routeId,
                        );

                      const sector =
                        sectors.find(
                          (x) =>
                            x.id ===
                            (
                              route?.sectorId ??
                              attempt
                                .routeSnapshot
                                ?.sectorId
                            ),
                        );

                      const routeName =
                        attempt.routeSnapshot?.name ?? route?.name;

                      const grade =
                        attempt.routeSnapshot?.grade ?? route?.grade;

                      if (
                        query.sector &&
                        !normalize(
                          sector?.name,
                        )?.includes(
                          normalize(
                            query.sector,
                          )!,
                        )
                      ) {
                        return false;
                      }

                      if (
                        query.route &&
                        !normalize(
                          routeName,
                        )?.includes(
                          normalize(
                            query.route,
                          )!,
                        )
                      ) {
                        return false;
                      }

                      if (
                        query.grade &&
                        normalize(
                          grade,
                        ) !==
                          normalize(
                            query.grade,
                          )
                      ) {
                        return false;
                      }

                      return true;
                    },
                  );

                if (!routeMatch) {
                  return false;
                }
              }

              return true;
            },
          );

        trainings.sort(
          (a, b) =>
            `${b.date}:${b.createdAt}`.localeCompare(
              `${a.date}:${a.createdAt}`,
            ),
        );

        trainings =
          trainings.slice(
            0,
            query.limit ??
              100,
          );

        const enriched =
          trainings.map(
            (training) => ({
              ...training,

              user:
                users.find(
                  (x) =>
                    x.id ===
                    training.userId,
                ),

              area:
                areas.find(
                  (x) =>
                    x.id ===
                    training.areaId,
                ),

              sectors: sectors.filter((sector) => (training.sectorIds ?? []).includes(sector.id)),

              gear:
                (
                  training.gearIds ??
                  []
                )
                  .map(
                    (
                      id: string,
                    ) =>
                      gear.find(
                        (x) =>
                          x.id ===
                          id,
                      ),
                  )
                  .filter(Boolean),

              routes:
                (
                  training.routes ??
                  []
                )
                  .filter(
                    (attempt: JsonObject) =>
                      query.includeTest ||
                      attempt.isTest !== true,
                  )
                  .map(
                  (
                    attempt: JsonObject,
                  ) => {
                    const route =
                      routes.find(
                        (x) =>
                          x.id ===
                          attempt.routeId,
                      );

                    const sector =
                      sectors.find(
                        (x) =>
                          x.id ===
                          (
                            route?.sectorId ??
                            attempt
                              .routeSnapshot
                              ?.sectorId
                          ),
                      );

                    return {
                      ...attempt,
                      route,
                      sector,
                    };
                  },
                ),
            }),
          );

        return {
          count:
            enriched.length,

          trainings:
            enriched,
        };
        });
      },
    }),
  };
}

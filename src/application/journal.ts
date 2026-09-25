import { Type, type Static, type TSchema } from "typebox";

export type JournalOperation<S extends TSchema = TSchema> = {
  name: string;
  label: string;
  description: string;
  parameters: S;
  execute(input: Static<S>): Promise<unknown>;
};

function operation<S extends TSchema>(definition: Omit<JournalOperation<S>, "execute">): JournalOperation<S> {
  return { ...definition, async execute() { throw new Error("FastAPI transport is required"); } };
}

const Ref = Type.Object({
  system: Type.String(),
  id: Type.Optional(Type.String()),
  url: Type.Optional(Type.String()),
}, { additionalProperties: false });

const User = Type.Object({
  id: Type.Optional(Type.String()),
  name: Type.Optional(Type.String()),
  externalRefs: Type.Optional(Type.Array(Ref)),
}, { additionalProperties: false });

const Area = Type.Object({
  id: Type.Optional(Type.String()),
  name: Type.Optional(Type.String()),
  country: Type.Optional(Type.String()),
  latitude: Type.Optional(Type.Number()),
  longitude: Type.Optional(Type.Number()),
  externalRefs: Type.Optional(Type.Array(Ref)),
}, { additionalProperties: false });

const Sector = Type.Object({
  id: Type.Optional(Type.String()),
  name: Type.Optional(Type.String()),
  externalRefs: Type.Optional(Type.Array(Ref)),
}, { additionalProperties: false });

const Weather = Type.Object({
  temperatureC: Type.Optional(Type.Number()),
  conditions: Type.Optional(Type.String()),
  wind: Type.Optional(Type.String()),
  humidity: Type.Optional(Type.String()),
  rockCondition: Type.Optional(Type.String()),
  notes: Type.Optional(Type.String()),
}, { additionalProperties: false });

const Result = Type.Union([
  Type.Literal("send"), Type.Literal("project"), Type.Literal("attempted"), Type.Literal("unknown"),
]);
const Style = Type.Union([
  Type.Literal("onsight"), Type.Literal("flash"), Type.Literal("redpoint"), Type.Literal("unknown"),
]);
const Belay = Type.Union([
  Type.Literal("lead"), Type.Literal("top_rope"), Type.Literal("auto_belay"),
  Type.Literal("bouldering"), Type.Literal("unknown"),
]);
const Feel = Type.Union([
  Type.Literal("easy"), Type.Literal("comfortable"), Type.Literal("limit"), Type.Literal("unknown"),
]);

const AttemptFields = {
  routeId: Type.Optional(Type.String()),
  name: Type.Optional(Type.String()),
  grade: Type.Optional(Type.String()),
  sector: Type.Optional(Sector),
  externalRefs: Type.Optional(Type.Array(Ref)),
  continueCurrentRoute: Type.Optional(Type.Boolean()),
  highPoint: Type.Optional(Type.Integer({ minimum: 0 })),
  totalMoves: Type.Optional(Type.Integer({ minimum: 1 })),
  falls: Type.Optional(Type.Integer({ minimum: 0 })),
  belay: Type.Optional(Belay),
  attempts: Type.Optional(Type.Integer({ minimum: 1 })),
  result: Type.Optional(Result),
  style: Type.Optional(Style),
  feel: Type.Optional(Feel),
  notes: Type.Optional(Type.String()),
  isTest: Type.Optional(Type.Boolean()),
};

const Attempt = Type.Object(AttemptFields, { additionalProperties: false });

export function createJournalTools() {
  return {
    start_climbing_training: operation({
      name: "start_climbing_training", label: "Start training", description: "Start an active training.",
      parameters: Type.Object({
        user: User,
        date: Type.Optional(Type.String()),
        startedAt: Type.Optional(Type.String()),
        environment: Type.Optional(Type.Union([Type.Literal("indoor"), Type.Literal("outdoor"), Type.Literal("unknown")])),
        area: Type.Optional(Area), sector: Type.Optional(Sector), weather: Type.Optional(Weather),
        gearIds: Type.Optional(Type.Array(Type.String())), notes: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
    }),

    append_climbing_attempt: operation({
      name: "append_climbing_attempt", label: "Add attempt", description: "Record one physical climbing attempt.",
      parameters: Type.Object({
        user: User, date: Type.Optional(Type.String()), area: Type.Optional(Area),
        ...AttemptFields,
      }, { additionalProperties: false }),
    }),

    update_climbing_attempt: operation({
      name: "update_climbing_attempt", label: "Correct attempt", description: "Correct an attempt, usually the last one.",
      parameters: Type.Object({
        user: User, attemptId: Type.Optional(Type.String()), useLastAttempt: Type.Optional(Type.Boolean()),
        highPoint: Type.Optional(Type.Integer({ minimum: 0 })),
        totalMoves: Type.Optional(Type.Integer({ minimum: 1 })), falls: Type.Optional(Type.Integer({ minimum: 0 })),
        result: Type.Optional(Result), style: Type.Optional(Style), feel: Type.Optional(Feel), notes: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
    }),

    delete_climbing_attempt: operation({
      name: "delete_climbing_attempt", label: "Delete attempt", description: "Delete an attempt, usually the last one.",
      parameters: Type.Object({
        user: User, attemptId: Type.Optional(Type.String()), useLastAttempt: Type.Optional(Type.Boolean()),
      }, { additionalProperties: false }),
    }),

    save_climbing_training: operation({
      name: "save_climbing_training", label: "Save training", description: "Save a completed training or merge its summary.",
      parameters: Type.Object({
        user: User, date: Type.String(), startedAt: Type.Optional(Type.String()),
        durationMinutes: Type.Optional(Type.Integer({ minimum: 1 })),
        environment: Type.Optional(Type.Union([Type.Literal("indoor"), Type.Literal("outdoor"), Type.Literal("unknown")])),
        area: Type.Optional(Area), sector: Type.Optional(Sector), weather: Type.Optional(Weather),
        gearIds: Type.Optional(Type.Array(Type.String())), routes: Type.Optional(Type.Array(Attempt)),
        physicalState: Type.Optional(Type.String()), notes: Type.Optional(Type.String()),
        mergeIntoActive: Type.Optional(Type.Boolean()),
      }, { additionalProperties: false }),
    }),

    update_climbing_training: operation({
      name: "update_climbing_training", label: "Update training", description: "Update active training metadata.",
      parameters: Type.Object({
        user: User, trainingId: Type.Optional(Type.String()),
        durationMinutes: Type.Optional(Type.Integer({ minimum: 1 })),
        environment: Type.Optional(Type.Union([Type.Literal("indoor"), Type.Literal("outdoor"), Type.Literal("unknown")])),
        area: Type.Optional(Area), sector: Type.Optional(Sector), weather: Type.Optional(Weather),
        gearIds: Type.Optional(Type.Array(Type.String())), physicalState: Type.Optional(Type.String()),
        notes: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
    }),

    finish_climbing_training: operation({
      name: "finish_climbing_training", label: "Finish training", description: "Finish the active training.",
      parameters: Type.Object({
        user: User, durationMinutes: Type.Optional(Type.Integer({ minimum: 1 })),
        physicalState: Type.Optional(Type.String()), notes: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
    }),

    get_current_climbing_training: operation({
      name: "get_current_climbing_training", label: "Current training", description: "Get active training summary or requested details.",
      parameters: Type.Object({
        user: User, detail: Type.Optional(Type.Union([Type.Literal("summary"), Type.Literal("full")])),
      }, { additionalProperties: false }),
    }),

    get_climbing_statistics: operation({
      name: "get_climbing_statistics", label: "Climbing statistics", description: "Calculate compact statistics in PostgreSQL.",
      parameters: Type.Object({
        user: User,
        scope: Type.Union([Type.Literal("week"), Type.Literal("month"), Type.Literal("custom"),
          Type.Literal("route"), Type.Literal("projects"), Type.Literal("records")]),
        dateFrom: Type.Optional(Type.String()), dateTo: Type.Optional(Type.String()),
        routeId: Type.Optional(Type.String()), route: Type.Optional(Type.String()),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
      }, { additionalProperties: false }),
    }),

    upsert_climbing_gear: operation({
      name: "upsert_climbing_gear", label: "Save gear", description: "Create or update climbing gear.",
      parameters: Type.Object({
        user: User,
        gear: Type.Object({
          id: Type.Optional(Type.String()),
          type: Type.Union([Type.Literal("shoes"), Type.Literal("rope"), Type.Literal("harness"),
            Type.Literal("belay_device"), Type.Literal("helmet"), Type.Literal("chalk"), Type.Literal("other")]),
          brand: Type.Optional(Type.String()), model: Type.Optional(Type.String()), size: Type.Optional(Type.String()),
          nickname: Type.Optional(Type.String()), active: Type.Optional(Type.Boolean()), notes: Type.Optional(Type.String()),
        }, { additionalProperties: false }),
      }, { additionalProperties: false }),
    }),

    find_climbing_routes: operation({
      name: "find_climbing_routes", label: "Find routes", description: "Search the route catalogue.",
      parameters: Type.Object({
        area: Type.Optional(Type.String()), sector: Type.Optional(Type.String()),
        name: Type.Optional(Type.String()), grade: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
    }),

    get_climbing_trainings: operation({
      name: "get_climbing_trainings", label: "Training history", description: "Read a limited, targeted training history.",
      parameters: Type.Object({
        userId: Type.Optional(Type.String()), userName: Type.Optional(Type.String()),
        status: Type.Optional(Type.Union([Type.Literal("active"), Type.Literal("completed")])),
        dateFrom: Type.Optional(Type.String()), dateTo: Type.Optional(Type.String()),
        area: Type.Optional(Type.String()), sector: Type.Optional(Type.String()),
        route: Type.Optional(Type.String()), grade: Type.Optional(Type.String()),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
        includeTest: Type.Optional(Type.Boolean()),
      }, { additionalProperties: false }),
    }),
  };
}

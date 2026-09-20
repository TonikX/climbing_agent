// Legacy persisted records remain permissive until an explicit data migration.
// New API contracts must not expose this internal type.
export type JsonObject = Record<string, any>;

# JSON MVP stabilization — 2026-09-20

The patch preserves existing entity IDs, JSON file names, and all eight tool names.
It does not migrate or rewrite historical data during deployment.

## Changes

- Resolve users by explicit ID or external identity without falling back to a
  same-name user. Reject conflicting identities and ambiguous name-only lookup.
- Return an empty history for an unknown user name; check gear ownership on writes.
- Merge summaries only when an existing event and an incoming entry uniquely
  identify each other. Never deduplicate individual append calls. Preserve
  fields omitted by a later summary, and retain declared sectors.
- Keep ambiguous repeated/aggregate summary entries separately. Consequently,
  repeating an ambiguous summary can still add entries; totals should be checked
  before treating such entries as independent physical attempts. Explicit event
  IDs and user-directed reconciliation are a future improvement.
- Do not inherit active-session location when saving a standalone training.
  Reject date mismatches instead of silently writing into another day's session.
- Resolve a supplied sector inside the active area, validate explicit catalogue
  IDs and hierarchy, and derive route snapshots from catalogue context.
- Unnamed routes stay snapshots. Named routes without a sector also stay
  snapshots until sufficient context is known. Catalogue grades are not overwritten.
- Prefer historical snapshot grade/name when filtering history. Allow sector
  history queries before a route has been logged and enrich training sectors.
- Use integer schemas for attempt counts and history limits, and derive input
  types from TypeBox. Legacy persisted records remain permissively typed.

## Storage guarantees and limits

Each tool holds an exclusive `.climbing-journal.lock` directory while performing
its synchronous operation. Cooperating plugin processes cannot interleave reads
and writes. Operations stage writes in memory and discard them on validation
failure. Each file is written to a unique temporary file, fsynced, then renamed;
training files are committed after referenced catalogues.

This is not a multi-file database transaction. A disk error or process crash can
leave part of a multi-file operation committed. External editors do not observe
the lock. PostgreSQL/API remains the appropriate next architectural step.

A busy lock returns an error rather than retrying a potentially non-idempotent
append. A killed process may leave a stale lock: stop all journal writers,
inspect the data and ensure no operation is running before removing that specific
empty lock directory. Never auto-delete the lock based on elapsed time alone.

`CLIMBING_JOURNAL_DATA_DIR` optionally selects another data directory. Tests use
a newly created OS temporary directory and never read or modify production data.
The production default remains `/root/.openclaw/workspace/data`.

User descriptors are identity selectors for a trusted OpenClaw agent, not an
authentication boundary. A future shared API must derive the current user from
authenticated client context; the existing administrative history tool can still
query all users when no user filter is supplied.

## Verification

`npm test` checks real SDK registration plus handler/file-storage regressions.
`npm run plugin:build` and `npm run plugin:validate` must both succeed before
`openclaw gateway restart`. Runtime verification uses:

```sh
openclaw plugins inspect climbing-journal --runtime --json
```

No weather service, external catalogue integration, schema migration, or backend
architecture rewrite is part of this patch. The existing climbing-journal skill
was reviewed and its climbing interpretation rules remain unchanged.

## Deployment result

- 29 tests passed on the production project using isolated temporary data.
- `plugin:build` and `plugin:validate` both succeeded before gateway restart.
- Runtime inspection: `status=loaded`, eight tools, empty `diagnostics`.
- Gateway systemd user service: `active`.
- Updated the old capability consent (previously only `save_climbing_training`)
  to the same eight requested journal tools; no other capabilities were added.
- Existing production JSON checksums matched the pre-deployment snapshot.
- Original source/build backup on the server:
  `/root/climbing-journal-backup-20260920T100030Z`.
- Deployment log and runtime inspection on the server:
  `/root/climbing-journal-review-20260920/deploy.log` and `runtime-final.json`.
- Telegram end-to-end message delivery was not tested by sending messages.

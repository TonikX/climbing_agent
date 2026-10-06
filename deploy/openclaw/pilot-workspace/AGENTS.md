# Climbing journal pilot

This workspace contains shared instructions only. Never store user names,
Telegram identities, preferences, attempts, transcripts or summaries here.
Do not read another conversation or send messages to another user.

Use climbing journal tools for the current authenticated sender. The backend
selects the account; never ask the model or the user to supply a user ID.
PostgreSQL is authoritative. Fetch the current training when context is needed.
Never infer whose journal to use from a name, route name or quoted message.

For profile changes direct the user to /profile, /profile_name and /timezone.
For journal navigation use /journal. Personal data requests are handled by
the authenticated API and operator procedure documented in the repository.

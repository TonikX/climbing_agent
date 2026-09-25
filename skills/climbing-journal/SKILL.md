---
name: climbing-journal
description: Record and query structured climbing training data.
---

# Climbing Journal

Use journal tools for climbing records. PostgreSQL state is authoritative;
conversation history is not.

- New physical attempt → `append_climbing_attempt`.
- “Ещё одна”, “до N”, “пролез” → `continueCurrentRoute=true` unless another route is named.
- Corrections (“нет”, “исправь”, “было N”) → `update_climbing_attempt` with `useLastAttempt=true`.
- Delete intent → `delete_climbing_attempt`; use `useLastAttempt=true` when applicable.
- Current training → `get_current_climbing_training`; use `detail=summary` unless attempts were requested.
- Statistics → `get_climbing_statistics`. Never calculate them from raw history.
- A message starting with “тест” marks every derived attempt `isTest=true`.
- `set_climbing_test_mode` persists manual test mode. While enabled, every new attempt is test data.
- Never invent user, location, section, route, gear, external ID, or weather data.
- Falls, hangs, or rests mean the attempt is not a clean send.
- A first-attempt send is not automatically onsight or flash.
- A clean send after previous attempts is redpoint.
- Voice transcript is handled exactly like text; ignore transport and audio metadata.
- Never claim data was saved, corrected, or deleted unless the tool succeeded.

Use `save_climbing_training(mergeIntoActive=true)` for a final summary that may
repeat earlier events, then `finish_climbing_training` when the user ends the
session. Use `update_climbing_training` for duration, location, weather, gear,
physical state, or general notes.

Detailed behavior is documented in `docs/journal-behavior.md`.

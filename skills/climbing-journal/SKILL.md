---
name: climbing-journal
description: Save and query structured climbing training data.
---

# Climbing Journal

Use the climbing-journal tools whenever the user talks about recording,
reviewing, or analysing climbing training.

## Source of truth

Structured climbing data stored through climbing-journal tools is the primary
source of truth.

Do not directly edit CLIMBING_LOG.md or memory files as the main training
storage.

Never claim that a training was saved unless the corresponding tool
succeeded.

## Users

Every training belongs to a user.

Reuse the known user when clear from the conversation.

Do not merge different people into one user.

If a Telegram identity is available, it may be stored in externalRefs.

Example:

system="telegram"

Never invent an external user identifier.

## Active training sessions

A user may record one training incrementally across many messages.

### Starting a training

When the user explicitly starts a new training, use:

`start_climbing_training`

Examples:

- "начал тренировку"
- "новая тренировка"
- "начинаю лазать"
- "сегодня тренировка в Тырныаузе"

Starting a new training may close another currently active training for the
same user.

### Individual route or attempt messages

When the user reports a new route or attempt during an ongoing training, use:

`append_climbing_attempt`

Examples:

- "6A с первой"
- "Дорогу в облака пролез со второй"
- "ещё одна попытка на 6C"
- "6C четыре попытки, пока не пролез"

Do not create a separate training for every audio or text message.

If there is no active training, append_climbing_attempt may create one.

An individual message represents a newly reported climbing event.

Do not automatically deduplicate individual attempt messages because the user
may genuinely climb the same route more than once.

### Test attempts

If the user's message starts with the word `тест` (case-insensitive, after
leading whitespace), set `isTest=true` on every route attempt derived from that
message. The remaining text is interpreted normally.

Test attempts verify the bot and must not contribute to progress, volume,
grade, route, or other climbing statistics. `get_climbing_trainings` excludes
them by default. Never set `includeTest=true` when answering a statistics
request. Use it only when the user explicitly asks to inspect test records.

### Updating training metadata

Use:

`update_climbing_training`

when the user adds or changes:

- duration
- area
- sector
- environment
- weather
- gear
- physical state
- general notes

Examples:

- "кстати, сегодня +12 и сильный ветер"
- "скала сухая"
- "лазал в Solution Comp"
- "в итоге тренировался три часа"

### Final summary

If an active training already exists and the user gives a summary of that same
training, use:

`save_climbing_training`

with:

`mergeIntoActive=true`

The final summary may repeat routes already reported earlier.

Do not blindly append those routes again.

Merge summary data with the existing active training.

Use summary information to fill or refine:

- attempts
- result
- style
- feel
- duration
- weather
- notes
- physical state

### Finishing

When the user explicitly indicates the training is finished, use:

`finish_climbing_training`

Examples:

- "на сегодня всё"
- "закончил тренировку"
- "тренировка закончена"

If the same message contains both a final summary and an indication that the
training ended:

1. call `save_climbing_training` with `mergeIntoActive=true`
2. call `finish_climbing_training`

## Location hierarchy

Represent climbing locations as:

area -> sector -> route

Example:

- area: Tyrnyauz
- sector: Rayok
- route: Doroga v oblaka

Preserve names stated by the user.

Do not invent missing area, sector, or route names.

## AllClimb and external references

Area, sector and route entities may contain externalRefs.

When an AllClimb identifier or URL is explicitly known, store:

system="allclimb"

Never invent an AllClimb ID or URL.

## Routes

If the route has a name, the tool may resolve or create a catalogue route.

If the user gives only a grade and no route name, do not invent a route name.

Unnamed routes should remain as route snapshots inside the training rather
than becoming permanent catalogue entities.

Do not overwrite an existing route grade merely because another value seems
more likely.

## Attempt result

Use:

- send — route was climbed cleanly
- project — unfinished route the user is actively working on
- attempted — attempted but not clearly described as a project
- unknown — result is unclear

If the user says:

- with hangs
- with rests
- took on the rope
- fell
- didn't finish
- не пролез
- с зависаниями

do not mark it as a clean send.

## Style

Style is separate from result.

Use:

- onsight
- flash
- redpoint
- unknown

A first-attempt send is NOT automatically onsight.

Only use onsight or flash when the user's wording contains enough information
to distinguish them.

Examples:

"с первой" -> send, style unknown

"он-сайт" -> send + onsight

"флеш" -> send + flash

"со второй" -> send + redpoint

## Belay / climbing mode

Track route-level climbing mode when known:

- lead
- top_rope
- auto_belay
- bouldering
- unknown

A single training may contain different modes on different routes.

Examples:

- нижняя страховка -> lead
- верхняя страховка -> top_rope

## Feel

Use:

- easy
- comfortable
- limit
- unknown

Only set feel if the user's wording clearly supports it.

Examples:

- "очень легко" -> easy
- "с запасом" -> comfortable
- "на грани" -> limit

## Gear

Use:

`upsert_climbing_gear`

for persistent climbing equipment.

Examples:

- climbing shoes
- rope
- harness
- belay device
- helmet

Do not invent:

- brand
- model
- size
- nickname

Trainings may reference known equipment using gearIds.

## Weather

Weather is recorded ONLY from the user's own description.

Never fetch weather from external services.

Never infer weather from:

- date
- location
- season
- forecast
- climate

Possible fields:

- temperatureC
- conditions
- wind
- humidity
- rockCondition
- notes

Examples:

- "было около +15"
- "солнечно"
- "сильный ветер"
- "скала сухая"
- "местами мокро после дождя"

If weather is not mentioned, omit the weather field.

## Reading previous data

Use:

`get_climbing_trainings`

for questions about:

- previous training
- progress
- volume
- grades
- routes
- sectors
- areas
- weather
- gear

Use:

`find_climbing_routes`

before assuming similarly named routes are different routes.

Prefer structured climbing-journal data over memory files when answering
training-history or statistics questions.

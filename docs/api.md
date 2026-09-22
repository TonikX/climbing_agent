# FastAPI MVP

Базовый URL снаружи: `https://<domain>/api/v1`.

Системные endpoints:

- `GET /health` — процесс отвечает, БД не проверяется;
- `GET /ready` — соединение с PostgreSQL работает;
- `GET /docs` — Swagger UI.

Внутренняя авторизация MVP:

```text
X-API-Key: значение INTERNAL_API_KEY
X-User-ID: внутренний user_* ID
```

`X-User-ID` используется только вместе с секретным ключом между OpenClaw и API.
Это не модель авторизации мобильного приложения.

## Минимальный сценарий

Разрешить или создать пользователя по Telegram ID:

```http
POST /api/v1/users/resolve
X-API-Key: ...

{"system":"telegram","external_id":"123456","name":"Антон"}
```

Начать тренировку:

```http
POST /api/v1/trainings
X-API-Key: ...
X-User-ID: user_...

{"date":"2026-09-21","environment":"outdoor"}
```

Добавить новое событие без автоматической дедупликации:

```http
POST /api/v1/trainings/training_.../attempts
X-API-Key: ...
X-User-ID: user_...

{"grade":"6A","attempts":1,"result":"send","style":"unknown","belay":"lead","is_test":false}
```

Для проверки бота передайте `is_test: true`. `GET /api/v1/trainings` по
умолчанию не возвращает такие пролазы; диагностический просмотр доступен с
`?include_test=true`.

Завершить тренировку:

```http
POST /api/v1/trainings/training_.../finish
X-API-Key: ...
X-User-ID: user_...

{"duration_minutes":180,"notes":"Хорошая тренировка"}
```

Полный контракт locations/sections/routes, gear, weather updates, summary merge,
idempotency keys и мобильная JWT-авторизация остаются следующими API-задачами.

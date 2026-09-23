# Climbing Journal

Персональный журнал скалолазных тренировок: OpenClaw/Telegram, FastAPI,
PostgreSQL и HTTPS через Nginx.

## Docker Compose

```text
Internet → Nginx → FastAPI → PostgreSQL
Telegram ↔ OpenClaw ────────────┘
```

Для серверного запуска скопируйте `.env.example` в `.env`, заполните секреты и
пути TLS, затем выполните `./scripts/deploy.sh`. Полная инструкция, перенос
существующего OpenClaw и backup описаны в
[`docs/docker-deployment.md`](docs/docker-deployment.md).

FastAPI MVP и примеры запросов: [`docs/api.md`](docs/api.md).

## Разработка

Нужен Node.js 24 (на сервере проверен 24.19.0).

```sh
npm ci
npm run build
npm test
npm run plugin:build
npm run plugin:validate
```

`npm ci` использует зафиксированные версии из `package-lock.json`.

## Структура

- `src/index.ts` — адаптер OpenClaw и сборка зависимостей.
- `src/application/journal.ts` — входные схемы восьми операций журнала.
- `src/domain/merge-attempts.ts` — правила сопоставления сводки и событий.
- `src/storage/api-client.ts` — передача всех операций из OpenClaw в FastAPI.
- `backend/` — FastAPI, SQLAlchemy и Alembic; начальная схема включает каталог
  locations/sections/routes, gear и журнал тренировок.
- `compose.yaml` — OpenClaw, API, PostgreSQL и Nginx.
- `deploy/` — образы OpenClaw и конфигурация Nginx.
- `skills/climbing-journal/SKILL.md` — инструкции агенту; исходник хранится в Git.
- `docs/api-plan.md` — целевая архитектура и порядок разработки API.
- `docs/deployment.md` — воспроизводимое развёртывание из Git.
- `backend/app/tool_service.py` — транзакционная реализация инструментов бота.

## Данные

PostgreSQL — единственный источник данных журнала. OpenClaw не читает и не
записывает локальные файлы с пользователями, тренировками, трассами или
снаряжением: все восемь инструментов выполняются через FastAPI в транзакции БД.
Перед развёртыванием делайте резервную копию PostgreSQL по инструкции из
`docs/docker-deployment.md`.

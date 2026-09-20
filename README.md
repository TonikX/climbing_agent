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
Тесты создают временные каталоги и не меняют рабочие данные.

## Структура

- `src/index.ts` — адаптер OpenClaw и сборка зависимостей.
- `src/application/journal.ts` — восемь операций журнала и их входные схемы,
  без импортов OpenClaw и файловой системы.
- `src/domain/merge-attempts.ts` — правила сопоставления сводки и событий.
- `src/storage/store.ts` — граница хранилища текущего JSON MVP.
- `src/storage/json-store.ts` — блокировка, чтение и запись JSON.
- `backend/` — FastAPI, SQLAlchemy и Alembic; начальная схема включает каталог
  locations/sections/routes, gear и журнал тренировок.
- `compose.yaml` — OpenClaw, API, PostgreSQL и Nginx.
- `deploy/` — образы OpenClaw и конфигурация Nginx.
- `skills/climbing-journal/SKILL.md` — инструкции агенту; исходник хранится в Git.
- `docs/api-plan.md` — целевая архитектура и порядок разработки API.
- `docs/deployment.md` — воспроизводимое развёртывание из Git.
- `REVIEW.md` — результаты предыдущей стабилизации JSON MVP.

Другой транспорт может создавать `createJournalService(createJsonStore(directory))`
и вызывать операции без загрузки OpenClaw. Он обязан валидировать входные данные
по `parameters` и разрешать пользователя из доверенного контекста.
Текущие дескрипторы пользователя не являются механизмом авторизации.

## Данные

В OpenClaw по умолчанию используется `/root/.openclaw/workspace/data`.
Для отдельного окружения задайте `CLIMBING_JOURNAL_DATA_DIR`.
Рабочие JSON, секреты, зависимости, резервные копии и сборка не хранятся в Git.

API уже поддерживает базовый жизненный цикл active training. TypeScript-плагин
пока сохраняет production-совместимое JSON-поведение; автоматической миграции
старых данных и скрытого переключения бота на неполный API нет.

# Climbing Journal

Персональный журнал скалолазных тренировок. Сейчас — OpenClaw/Telegram и JSON;
следующий этап — общий backend API для Telegram и мобильного приложения.

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

Перенос модулей не меняет форматы данных, IDs, восемь инструментов или правила
логирования. HTTP API и миграция в PostgreSQL в этом изменении ещё не реализованы.

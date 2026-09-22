# Развёртывание Docker Compose

Ветка поднимает четыре постоянно работающих сервиса:

```text
Internet → Nginx :80/:443 → FastAPI :8000 → PostgreSQL :5432
Telegram/OpenAI ↔ OpenClaw Gateway ───────────┘
```

FastAPI не публикует порт на хост. Gateway публикуется только на
`127.0.0.1:18789` для SSH-туннеля. PostgreSQL доступен только локально на
`127.0.0.1:15432`, чтобы администратор мог подключиться через SSH tunnel.
Nginx — единственная публичная точка входа.

## Что уже работает

FastAPI содержит health/readiness, разрешение пользователя по external identity,
создание и чтение тренировок, добавление отдельного route event и завершение
тренировки. Начальная схема PostgreSQL также содержит locations, sections,
routes, gear, связи тренировок, external refs и idempotency keys. Каталожные
HTTP endpoints будут добавлены следующим этапом. Схема создаётся Alembic.

OpenClaw и существующий TypeScript-плагин включены в образ. Пока плагин продолжает
писать legacy JSON в persistent workspace. Переключение всех восьми инструментов
на HTTP API — отдельный этап после переноса полной merge/gear/catalog logic и
проверяемого импорта JSON. Автоматическая миграция данных намеренно отсутствует.

## Требования к серверу

- Ubuntu 24.04;
- Docker Engine и Docker Compose v2;
- домен, A/AAAA-запись которого указывает на сервер;
- открытые TCP 80 и 443;
- закрытые извне PostgreSQL 5432 и OpenClaw 18789;
- действующий TLS-сертификат.

Если на хосте уже работает Nginx, задайте для Compose другой HTTP bind, например
`NGINX_HTTP_HOST=127.0.0.1` и `NGINX_HTTP_PORT=18080`. HTTPS-порт можно оставить
443, если он свободен. Системный Nginx при этом обслуживает ACME challenge и
перенаправляет домен на HTTPS.

## Первый запуск

Клонировать нужную ветку в `/srv/climbing-journal/app`, затем:

```sh
cd /srv/climbing-journal/app
cp .env.example .env
chmod 600 .env
```

Заменить все `replace-*`, пути сертификатов и домен. Секреты генерировать
независимо командой `openssl rand -hex 32`.

Создать persistent-каталоги из `.env` и дать UID 1000 контейнера OpenClaw права
на них:

```sh
install -d -m 700 /srv/climbing-journal/openclaw/config
install -d -m 755 /srv/climbing-journal/openclaw/workspace
install -d -m 700 /srv/climbing-journal/openclaw/auth-secrets
install -d -m 755 /srv/climbing-journal/certbot
chown -R 1000:1000 /srv/climbing-journal/openclaw
```

### TLS

До первого старта получить сертификат. Например, когда порт 80 свободен:

```sh
certbot certonly --standalone -d api.example.com
```

Указать полученные `fullchain.pem` и `privkey.pem` в `.env`. После первого запуска
Nginx обслуживает `/.well-known/acme-challenge/` из `CERTBOT_WEBROOT_HOST_DIR`,
поэтому продление можно настроить через webroot и reload Nginx после успешного
renewal. Проверить права чтения каталогов `/etc/letsencrypt` Docker daemon-ом.

### Существующий OpenClaw

Перед переключением остановить старый systemd Gateway, иначе два экземпляра
Telegram polling будут конфликтовать:

```sh
systemctl --user stop openclaw-gateway.service
systemctl --user disable openclaw-gateway.service
```

Сначала сделать резервную копию `/root/.openclaw`. Перенести содержимое state и
workspace в каталоги из `.env`, сохранив владельца UID 1000. В `openclaw.json`
заменить старый путь плагина `/root/climbing-journal` на
`/opt/climbing-journal`, либо после запуска переустановить link командой ниже.
Не запускать `openclaw-bootstrap.sh` поверх существующего state.

Для полностью новой установки после заполнения `.env`:

```sh
./scripts/openclaw-bootstrap.sh
```

Для перенесённой установки зарегистрировать встроенный в образ плагин:

```sh
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js plugins install --link /opt/climbing-journal --force --accept-capabilities
```

Запуск всего стека:

```sh
./scripts/deploy.sh
```

## Проверка

```sh
docker compose ps
curl -fsS https://api.example.com/health
curl -fsS https://api.example.com/ready
docker compose logs --tail=100 api nginx openclaw-gateway postgres
docker compose run --rm openclaw-cli plugins inspect climbing-journal --runtime --json
```

### Перенос существующего JSON-журнала

Перед первым переносом сделайте копию каталога `workspace/data`. Затем соберите
шесть JSON-массивов (`users`, `areas`, `sectors`, `routes`, `gear`, `trainings`)
в один объект и отправьте его запросом `PUT /api/v1/journal/snapshot` с заголовком
`X-API-Key`. Повторный запрос безопасен: записи обновляются по их ID, а попытки
маршрутов пересобираются для каждой тренировки. Старые записи тренировок без
`userId` пропускаются и возвращаются в `skipped_training_ids`.

На сервере из каталога проекта это выполняет готовый скрипт:

```bash
./scripts/import-json-snapshot.sh
```

После переноса новые изменения синхронизируются плагином автоматически. При
ошибке API инструмент OpenClaw сообщает об ошибке вместо подтверждения записи;
данные при этом остаются в локальной JSON-копии и попадут в БД при следующей
успешной синхронизации.

### DeepSeek V4 Flash через Cloud.ru

Задайте `CLOUDRU_API_KEY` в `.env`, затем примените конфигурацию провайдера:

```bash
docker cp deploy/openclaw/cloudru-deepseek.json climbing-journal-openclaw-gateway-1:/tmp/cloudru-deepseek.json
docker compose exec openclaw-gateway node dist/index.js config patch --file /tmp/cloudru-deepseek.json
docker compose restart openclaw-gateway
```

Основной моделью и моделью heartbeat станет
`cloudru/deepseek-ai/DeepSeek-V4-Flash`; `openrouter/auto` останется резервом.
Периодический heartbeat отключён параметром `every: "0m"`, чтобы не выполнять
фоновые обращения к модели без настроенной задачи.

Для голосовых сообщений используется отдельная Audio-to-Text модель
`openai/whisper-large-v3` через OpenAI-совместимый endpoint Cloud.ru. Для
транскрибации OpenClaw берёт `CLOUDRU_API_KEY` из окружения. Текстовые ответы
продолжает генерировать DeepSeek V4 Flash. После применения конфигурации
перезапустите Gateway и проверьте голосовое сообщение в Telegram.

Swagger UI доступен по `/docs`. До появления пользовательской JWT-авторизации
операции API защищены `X-API-Key`; операции тренировок также требуют внутренний
`X-User-ID`. Этот ключ предназначен только для OpenClaw и не должен попадать в
мобильное приложение.

## Обновление и откат

```sh
git pull --ff-only
./scripts/deploy.sh
```

Перед обновлением БД выполнить backup. Alembic запускается при старте API.
Для отката кода checkout предыдущего проверенного commit и повторная сборка.
Откат схемы БД автоматически не выполнять: сначала проверить совместимость и
сохранить свежий backup.

## Backup PostgreSQL

Пример ручного backup без публикации порта БД:

```sh
docker compose exec -T postgres pg_dump -U climbing -d climbing_journal -Fc \
  > /srv/climbing-journal/backups/climbing-$(date -u +%Y%m%dT%H%M%SZ).dump
```

Backup необходимо копировать на другой сервер или объектное хранилище и
периодически проверять восстановление в отдельную базу.

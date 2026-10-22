# Веб-вход через Telegram

Развёрнуто 22.10.2026: `https://132-243-114-242.sslip.io/`, миграция `20261022_0019`.
До обновления сохранены БД, конфигурация и прежний API-образ:
`/srv/climbing-journal/backups/web-auth-20261022T093646Z/`.
Проверены HTTPS, здоровый API, 401 без сессии, 404 для internal API,
переход на форму Telegram и доступ к JWKS из API-контейнера.
Пройдены 12 серверных тестов на отдельном временном PostgreSQL и 3 теста web API-клиента.

Используется OIDC Authorization Code + PKCE S256, `openid profile`.
Проверка подписи и claims выполняется Authlib; отдельный UserInfo-запрос не нужен.
Идентичность берётся из подтверждённого Telegram `id`, не из OIDC `sub`.
Веб-вход не создаёт пользователей и не выдаёт одобрение: неизвестный,
ожидающий одобрения или заблокированный аккаунт не получает сессию.

## Настройка

В @BotFather → бот → Login Widget зарегистрировать origin сайта и точный
redirect URI `https://YOUR_HOST/api/v1/auth/telegram/callback`.
В защищённом `.env.public` задать:

```dotenv
WEB_ORIGIN=https://YOUR_HOST
TELEGRAM_OIDC_CLIENT_ID=YOUR_CLIENT_ID
TELEGRAM_OIDC_CLIENT_SECRET=YOUR_CLIENT_SECRET
```

Secret — отдельное значение из Login Widget, не токен Telegram-бота.
Не добавлять его в git, VITE-переменные, адрес страницы или frontend-сборку.
API теперь подключён к существующей сети egress для token/JWKS запросов.
PostgreSQL остаётся во внутренней сети.

Выполнить миграцию `20261022_0019` штатным migrate-сервисом, собрать API и nginx:

```sh
docker compose --env-file .env.public -f compose.public.yaml build api nginx
docker compose --env-file .env.public -f compose.public.yaml run --rm migrate
docker compose --env-file .env.public -f compose.public.yaml up -d api bot worker-fast worker-ai worker-delivery nginx
```

Сборка nginx включает `web/dist`; Node-процесс в production не запускается.
Сохранены запреты internal/tools и маршрут Telegram webhook. Старый образ nginx
не содержит frontend: при откате нужен совместимый образ и конфигурация nginx.
Миграция добавочная, старые bot-сессии сохраняются с `channel=bot`.

## Контракт и защита

- `GET /api/v1/auth/config` → `telegramLoginEnabled`.
- `GET /api/v1/auth/telegram/start` → Telegram, браузерная cookie на 10 минут.
- `GET /api/v1/auth/telegram/callback` → проверка и редирект на `/`.
- `GET /api/v1/auth/session` → профиль, срок сессии, CSRF token.
- `POST /api/v1/auth/logout`, `/logout-all` → 204, удаление cookie.

Одноразовое состояние, nonce, PKCE verifier и hash привязки к браузеру хранятся
в PostgreSQL `web_login_states`. Таблица закрыта RLS от runtime/importer.
Состояние потребляется атомарным DELETE RETURNING, включая ошибку провайдера.
Повторный callback и вход из другого браузера отклоняются.
Истёкшие состояния удаляются при начале следующего входа.

Cookie `__Host-climbing_session`: Secure, HttpOnly, SameSite=Lax, Path=/, без Domain.
Сессия действует 24 часа, хранится в `auth_sessions` как SHA-256 hash с channel=web.
Срок bot Bearer-сессий остаётся 15 минут. Блокировка и общий выход отзывают оба
типа сессий. Противоречивые Bearer/cookie credentials отклоняются.

Любые изменяющие запросы с cookie требуют точного Origin=WEB_ORIGIN и
`X-CSRF-Token` из `/auth/session`. Token привязан к сессии, хранится только в памяти
клиента и не является credential. Bearer API остаётся совместимым.
Токены Telegram не сохраняются; запросов к LLM при входе и просмотре нет.

Ошибки callback возвращаются только как фиксированные коды `expired`, `failed`,
`cancelled`, `approval`. Секреты и ответы token endpoint не попадают в журнал.
Access log nginx/API выключен, Referrer-Policy=no-referrer. Start ограничен по IP.
Upstream API/бота обновляется через Docker DNS без перезапуска nginx при смене IP.
Для callback подавлены request-level error logs: они могли бы содержать OAuth code
при недоступности upstream. Диагностика API остаётся без payload и query-параметров.

Для локальной проверки cookie нужен HTTPS origin, зарегистрированный в BotFather;
обычный HTTP Vite подходит для деморежима. Не ослаблять Secure для production.

Официальные источники:
[Telegram Login](https://core.telegram.org/bots/telegram-login),
[Authlib web clients](https://docs.authlib.org/en/latest/oauth2/client/web/).

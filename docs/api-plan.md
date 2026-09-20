# Подготовка общего API

Статус: план следующего этапа, не описание уже работающих HTTP endpoints.

## Границы

```text
Telegram → OpenClaw adapter ─┐
                            ├→ Backend API → application → repositories → PostgreSQL
Mobile → text/voice client ──┘
```

Пока OpenClaw напрямую вызывает `createJournalService` с JSON-хранилищем.
Следующий адаптер HTTP использует те же операции; после появления общего API
OpenClaw становится его клиентом. Мобильное приложение не зависит от OpenClaw.

Уже отделены application, merge-логика и JSON I/O. Текущий `JournalStore`
синхронный и работает с массивами legacy records. Это временная граница MVP,
а не готовый контракт PostgreSQL. Перед SQL нужны типизированные сущности,
асинхронные repositories и настоящая транзакция на команду. Нельзя просто
подставить SQL-запросы в синхронные callbacks текущего хранилища.

## Контракты v1

Все пользовательские endpoints получают владельца из проверенной авторизации.
`userId` из произвольного JSON или Telegram-сообщения не даёт доступа к данным.
Telegram external reference сопоставляется с пользователем через доверенный
контекст бота; мобильный токен — через выбранный auth provider.
Авторизация будет частью собственного backend; конкретный механизм для мобильного
клиента проектируется отдельно. Supabase не используется.

| Метод и путь | Назначение |
| --- | --- |
| `POST /v1/trainings` | Создать active или completed тренировку; режим явный |
| `GET /v1/trainings` | История текущего пользователя, фильтры и cursor pagination |
| `GET /v1/trainings/{id}` | Тренировка своего пользователя |
| `PATCH /v1/trainings/{id}` | Обновить только переданные metadata |
| `POST /v1/trainings/{id}/attempts` | Добавить новое событие; не дедуплицировать по трассе |
| `POST /v1/trainings/{id}/summary` | Сопоставить итог со старыми событиями |
| `POST /v1/trainings/{id}/finish` | Завершить тренировку; повторное завершение безопасно |
| `GET /v1/gear` | Снаряжение пользователя |
| `POST /v1/gear` | Создать снаряжение |
| `PATCH /v1/gear/{id}` | Изменить своё снаряжение |
| `GET /v1/locations` | Outdoor areas и gyms |
| `GET /v1/locations/{id}/sections` | Секторы, зоны и стены |
| `GET /v1/routes` | Каталог по location, section, name и grade |

До реализации нужны отдельные схемы HTTP requests/responses и OpenAPI-документ.
Legacy `JsonObject` наружу не отдаётся. Ошибки имеют стабильные коды и requestId:
validation — 400, unauthenticated — 401, отсутствующий/чужой ресурс — 404,
конфликт активной сессии, версии или ключа — 409.

### Повторы, конкурентность и summary

- `Idempotency-Key` у команд связывается с пользователем, операцией и хешем
  запроса. Повтор того же запроса возвращает сохранённый результат; другой
  payload под тем же ключом даёт 409. Ключ и изменение пишутся одной транзакцией.
- Два разных сообщения об одной трассе с разными ключами — два события.
- Каждое новое route event получает свой ID. Уточнение может ссылаться на него.
  `routeId` обозначает трассу, а не уникальный пролаз.
- PATCH и summary используют версию тренировки для защиты от lost update.
- Ограничение одной active session на пользователя обеспечивается БД.
  Закрытие старой при явном старте новой выполняется одной транзакцией.
- Неоднозначный summary в будущем возвращает кандидатов для уточнения.
  Текущий JSON MVP сохраняет неоднозначные записи отдельно — этот переход
  поведения должен быть явно согласован и покрыт контрактными тестами.
- Суммарное число attempts не распределяется по событиям без явного соответствия.

## Модель PostgreSQL

- `users`, `external_refs`: внутренние IDs независимы от Telegram/AllClimb.
- `locations`: `type=outdoor|gym`, name, country, city, coordinates.
- `sections`: location_id, `type=sector|zone|wall`, name.
- `routes`: section_id, name, grade; nullable color, route_number, setter,
  set_date, removed_at для indoor.
- `gear`: user_id, type и характеристики.
- `training_sessions`: user_id, status, local date, IANA timezone, timestamps,
  duration, physical state, notes, user-reported weather и version.
- `training_sections`, `training_gear`: связи с секторами и снаряжением.
- `route_attempts`: собственный ID, training_id, nullable route_id, snapshot,
  attempts, result, style, belay, feel, notes и порядок событий.
- `idempotency_keys`: владелец, операция, ключ, hash запроса и сохранённый ответ.

Существующие `prefix_UUID` IDs сохраняются как text keys при первой миграции.
`areas` становятся outdoor locations, `sectors` — sections типа sector без
смены IDs. Исторические route snapshots сохраняются независимо от каталога.
Unnamed маршруты не создают каталог автоматически. Ссылки `external_refs`
получают явное владение и уникальность в пределах источника и типа сущности.

## Порядок реализации

1. Утвердить auth и границу доверия Telegram; определить timezone пользователя.
2. Описать типизированные entities, HTTP-схемы, OpenAPI и ошибки.
3. Начальная PostgreSQL schema уже включает locations/sections/routes/gear,
   связи тренировок, external refs и idempotency keys. Следующий шаг — полные
   async repositories и HTTP endpoints поверх этих таблиц.
4. Подготовить отдельный dry-run importer legacy JSON: валидация, отчёт о
   неоднозначностях, сохранение IDs, backup и сверка количества/ссылок.
   Никакой автоматической миграции при старте сервера.
5. Реализовать API для trainings/attempts/gear с транзакциями и idempotency.
6. Проверить контрактами разделение пользователей, конкурентные append/start,
   повторы, summary, unnamed routes и rollback.
7. Переключить OpenClaw на API после проверки данных и плана отката.
8. Добавить мобильный клиент: отдельно audio → text, отдельно text → commands.

Погода остаётся только со слов пользователя. Импортеры внешних каталогов и
социальные публикации не входят в первый API milestone.

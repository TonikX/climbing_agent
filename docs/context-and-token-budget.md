# Контекст и расход токенов

## Runtime flow

```text
Telegram voice → Cloud.ru Whisper → transcript → DeepSeek → compact tool call
→ FastAPI → PostgreSQL → compact tool result
```

OpenClaw передаёт Telegram DM не более двух последних сообщений. Голосовой
transport передаёт модели текст расшифровки; идентификаторы Telegram, файл и
метаданные аудио не являются частью journal tool payload.

FastAPI восстанавливает активную тренировку, текущую трассу и последнюю попытку
из PostgreSQL. Поэтому `continueCurrentRoute=true` и `useLastAttempt=true`
работают после перезапуска OpenClaw без replay истории тренировки.

## Progressive retrieval

- `get_current_climbing_training(detail="summary")` возвращает агрегаты без attempts.
- `detail="full"` используется только по явному запросу попыток.
- `get_climbing_statistics` считает week/month/custom/route/projects/records в БД
  и не возвращает сырые попытки.
- `get_climbing_trainings` предназначен для точечного просмотра и ограничен 100
  тренировками; projects ограничены 50, по умолчанию 10.
- Тестовые попытки исключаются из current summary и statistics.

## Метрики

OpenClaw сохраняет provider/model и provider-reported token usage в собственной
session SQLite. Не нужно повторно оценивать токены по тексту. Плагин отдельно
пишет безопасную строку `[climbing-journal-metrics]` с именем tool, размером
результата в байтах и latency; аргументы, transcript и prompt не логируются.

Для сравнения milestone выполнить четыре сценария:

1. «Ещё одна, до 14»;
2. «Нет, было два срыва»;
3. «Покажи текущую тренировку»;
4. «Как прошла эта неделя?».

Сопоставить `inputTokens`, `outputTokens`, latency и `resultBytes`. Первые два
сценария не должны получать TrainingSession или список attempts. Недельная
статистика получает только агрегаты. Полные attempts допустимы лишь в третьем
сценарии при `detail="full"`.

Dynamic tool subsets не реализуются в `defineToolPlugin`: текущий SDK публикует
статический набор. Это отдельная оптимизация после измерений; backend state,
короткий skill, компактные schemas/results и history window уже применены.

Статический размер исходников постоянного runtime prefix после рефакторинга:

| Часть | До | После |
| --- | ---: | ---: |
| Tool schemas/application module | 52 547 B | 10 191 B |
| Runtime `SKILL.md` | 7 411 B | 1 651 B |

Это вспомогательная метрика размера, а не замена provider-reported token usage.

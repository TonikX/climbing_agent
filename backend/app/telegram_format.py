"""Pure Telegram formatter: identical output for buttons and interpreted requests."""
import json


def button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def menu(active: bool = False) -> list:
    return [[button("Завершить тренировку" if active else "Начать тренировку", "training:finish" if active else "training:start")],
            [button("✍️ Записать попытку без AI", "attempt:form")],
            [button("📍 Место тренировки", "training:location")],
            [button("📋 Все попытки", "training:details:current"), button("📊 Статистика", "stats:menu")],
            [button("👤 Профиль", "profile"), button("🧪 Тестовый режим", "test:menu")]]


def stats_menu() -> list:
    return [[button("🧗 Текущая тренировка", "stats:current")],
            [button("🕘 Последняя тренировка", "stats:last-training")],
            [button("📅 Эта неделя", "stats:week"), button("🗓 Этот месяц", "stats:month")],
            [button("📈 Прогресс", "stats:progress"), button("🎯 По категориям", "stats:grades")],
            [button("📍 По локациям", "stats:locations"), button("🔄 Проекты", "stats:projects")],
            [button("🏆 Рекорды", "stats:records")], [button("← Главное меню", "journal")]]


def summary(dto: dict) -> str:
    value = dto.get("summary", dto)
    lines = [f"{value.get('routesCount', 0)} трасс · {value.get('attemptsCount', 0)} попыток",
             f"🏁 {value.get('reachedTopRoutes', value.get('reachedTopCount', 0))} — дошёл до конца",
             f"✅ {value.get('completedRoutes', 0)} — чисто",
             f"❓ {value.get('unknownCleanRoutes', 0)} — чистота не уточнена",
             f"👁 {value.get('onsightCount', 0)} Onsight", f"⚡ {value.get('flashCount', 0)} Flash",
             f"🎯 {value.get('redpointCount', 0)} Red Point",
             f"❔ {value.get('unknownStyleCount', 0)} — стиль не указан",
             f"🔄 {value.get('activeProjects', 0)} проекта"]
    for key, label in (("maxAttemptedGrade", "пробовал"), ("maxReachedTopGrade", "дошёл до конца"), ("maxCompletedGrade", "чисто")):
        if value.get(key):
            lines.append(f"Максимум {label}: {value[key]}")
    for key, label in (("leadAttemptsCount", "Нижняя страховка"), ("topRopeAttemptsCount", "Верхняя страховка"),
                       ("autoBelayAttemptsCount", "Автостраховка"), ("boulderingAttemptsCount", "Боулдеринг"),
                       ("unknownBelayAttemptsCount", "Страховка не указана")):
        lines.append(f"{label}: {value.get(key, 0)}")
    return "\n".join(lines)


def statistics(dto: dict) -> str:
    value = dto.get("training", dto)
    if value is None or dto.get("active") is False:
        return "Тренировка не найдена."
    labels = {"week": "📅 Эта неделя", "month": "🗓 Этот месяц", "last_training": "🕘 Последняя тренировка",
              "progress": "📈 Прогресс", "grades": "🎯 По категориям", "locations": "📍 По локациям",
              "projects": "🔄 Проекты", "records": "🏆 Рекорды"}
    lines = [labels.get(dto.get("scope"), "🧗 Текущая тренировка")]
    location = value.get("location") or {}
    if location.get("name"):
        lines.append(location["name"])
    if value.get("date"):
        lines.append(value["date"])
    if "trainingsCount" in value:
        lines.append(f"{value['trainingsCount']} тренировок")
    lines.append(summary(value))
    for key in ("grades", "locations", "projects", "periods"):
        for row in dto.get(key, [])[:15]:
            title = row.get("grade") or (row.get("location") or {}).get("name") or row.get("name") or row.get("period", "")
            if key == "projects":
                route = row.get("route") or {}
                lines.append(f"\n{route.get('name') or 'Трасса'} {route.get('grade') or ''}\nТочка: {row.get('highPoint')} / {row.get('totalMoves')}")
            else:
                lines.append(f"\n{title}\n{summary(row)}")
    if dto.get("records"):
        labels = {"highestCompletedGrade": "Чисто", "highestFlashGrade": "Flash", "highestRedpointGrade": "Red Point",
                  "totalTrainings": "Тренировок", "totalAttempts": "Попыток", "totalCompletedRoutes": "Чистых трасс"}
        lines.append("\n" + "\n".join(f"{labels.get(k, k)}: {v if v is not None else 'нет данных'}" for k, v in dto["records"].items()))
    return "\n".join(lines)


def attempts(dto: dict) -> list[str]:
    lines = []
    # get_current returns route groups; history returns individual attempts.
    for route in dto.get("routes", []):
        records = route.get("attempts")
        if not isinstance(records, list):
            records = [route]
        metadata = route.get("route") or route.get("routeSnapshot") or route
        title = f"{metadata.get('name', 'Трасса')} {metadata.get('grade') or ''}".strip()
        for attempt in records:
            yn = lambda v: "да" if v is True else "нет" if v is False else "не уточнено"
            lines.append(f"{title}" + (" · 🧪 тест" if attempt.get("isTest") else "") + f"\n• Дошёл до конца: {yn(attempt.get('reachedTop'))}\n"
                         f"• Пролез чисто: {yn(attempt.get('cleanAscent'))}\n"
                         f"• Стиль: {attempt.get('style', 'unknown')}\n"
                         f"• Страховка: {attempt.get('belay', 'unknown')}\n"
                         f"• Срывы: {attempt.get('falls') if attempt.get('falls') is not None else 'не уточнено'}" +
                         f"\n• Зависания: {attempt.get('hangs') if attempt.get('hangs') is not None else 'не уточнено'}" +
                         (f"\n• Комментарий: {attempt['notes']}" if attempt.get("notes") else ""))
    chunks, current = [], "📋 Все попытки\n"
    for line in lines:
        if len(current) + len(line) > 3500:
            chunks.append(current)
            current = ""
        current += "\n" + line[:3400] + "\n"
    return chunks + [current if lines else "Попыток пока нет."]

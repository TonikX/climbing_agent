"""Pure Telegram formatter: identical output for buttons and interpreted requests."""
import json
import re


def grade_table(rows):
    cells = [(str(row['grade']).replace('\n', ' ').replace('\r', ' ')[:12],
              str(row.get('routesCount', 0)), str(row.get('attemptsCount', 0)),
              f"{row.get('completedRoutes', 0)} ({_percent(row.get('completionRate'))})") for row in rows]
    headers = ('Кат.', 'Трасс', 'Поп.', 'Чисто')
    widths = [max(len(row[i]) for row in [headers, *cells]) for i in range(4)]
    def border(left, middle, right):
        return left + middle.join('─' * (width + 2) for width in widths) + right
    def line(row):
        return '│ ' + ' │ '.join(value.ljust(widths[i]) if i == 0 else value.rjust(widths[i])
                                  for i, value in enumerate(row)) + ' │'
    return '\n'.join([border('┌', '┬', '┐'), line(headers), border('├', '┼', '┤'),
                      *(line(row) for row in cells), border('└', '┴', '┘')])


def table_entities(value):
    """Telegram offsets are UTF-16 units, including emoji before a table."""
    return [{'type': 'pre', 'offset': len(value[:m.start()].encode('utf-16-le')) // 2,
             'length': len(m.group().encode('utf-16-le')) // 2}
            for m in re.finditer(r'(?m)^[┌│├└][^\n]*(?:\n[┌│├└][^\n]*)*', value)]


def button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


STYLE_NAMES = {"onsight": "Onsight", "flash": "Flash", "redpoint": "Red Point",
               "with_falls": "Со срывом", "with_hangs": "С зависанием", "top_rope": "Верхняя", "unknown": "Не указан"}
BELAY_NAMES = {"lead": "Нижняя", "top_rope": "Верхняя", "auto_belay": "Автостраховка",
               "bouldering": "Боулдеринг", "unknown": "Не указана"}


def ascent_card(item, region=None, sector=None):
    from app.route_input import route_name
    from app.grades import normalize_grade
    snapshot = item.route_snapshot or {}
    return (("🧪 Тестовая запись — не учитывается в статистике.\n" if item.is_test else "") +
            f"Регион: {region or 'Не указан'}\nСектор: {sector or 'Не указан'}\n"
            f"Название трассы: {route_name(snapshot.get('name')) or 'Не указано'}\nКатегория: {normalize_grade(snapshot.get('grade')) or 'Не указана'}\n"
            f"Чисто: {'Да' if item.clean_ascent is True else 'Нет'}\n"
            f"Стиль: {STYLE_NAMES.get(item.style, item.style)}\n"
            f"Страховка: {BELAY_NAMES.get(item.belay, item.belay)}")


def menu(active: bool = False) -> list:
    return [[button("🧗 Текущая тренировка" if active else "Начать тренировку", "training:details:current" if active else "training:start")],
            *([] if active else [[button("↩️ Возобновить последнюю тренировку", "training:resume")]]),
            [button("✏️ Тренировки и пролазы", "trainings:0")],
            [button("📊 Статистика", "stats:menu")],
            [button("👤 Профиль", "profile"), button("🧪 Тестовый режим", "test:menu")]]


MENU_COMMANDS = {item["text"]: item["callback_data"] for active in (False, True) for row in menu(active) for item in row}
MENU_COMMANDS["🏠 Главное меню"] = "journal"
MENU_COMMANDS["Журнал тренировок"] = "journal"
MENU_COMMANDS["🧗 Журнал тренировок"] = "journal"


def reply_menu(active=False):
    return {"keyboard": [[{"text": item["text"]} for item in row] for row in menu(active)] +
            [[{"text": "🏠 Главное меню"}]], "resize_keyboard": True, "is_persistent": True}


def stats_menu() -> list:
    return [[button("🧗 Текущая тренировка", "stats:current")],
            [button("🕘 Последняя тренировка", "stats:last-training")],
            [button("📅 Эта неделя", "stats:week"), button("🗓 Этот месяц", "stats:month")],
            [button("📈 Прогресс", "stats:progress"), button("🎯 По категориям", "stats:grades")],
            [button("📍 По локациям", "stats:locations"), button("🔄 Проекты", "stats:projects")],
            [button("🏆 Рекорды", "stats:records")], [button("← Главное меню", "journal")]]


def _number(value):
    return "—" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _duration(minutes):
    if minutes is None:
        return ""
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} ч {rest} мин" if hours else f"{rest} мин"


def _percent(value):
    return "—" if value is None else f"{value:.0%}"


def summary(dto: dict) -> str:
    value = dto.get("summary", dto)
    lines = [f"{value.get('routesCount', 0)} трасс · {value.get('attemptsCount', 0)} попыток",
             f"🏁 Дошёл: {value.get('reachedTopRoutes', value.get('reachedTopCount', 0))} · "
             f"✅ Чисто: {value.get('completedRoutes', 0)} · 🔄 Проекты: {value.get('activeProjects', 0)}"]
    if value.get("unknownCleanRoutes"):
        lines.append(f"❓ Чистота не уточнена: {value['unknownCleanRoutes']}")
    styles = [f"{label}: {value[key]}" for key, label in (
        ("onsightCount", "👁 Onsight"), ("flashCount", "⚡ Flash"),
        ("redpointCount", "🎯 Red Point"), ("unknownStyleCount", "Стиль не указан")) if value.get(key)]
    if styles:
        lines.append(" · ".join(styles))
    weighted = [f"{label}: {value[key]} попыток" for key, label in (
        ("topRopeStyleAttemptsCount", "Верхняя (стиль)"), ("withFallsAttemptsCount", "Со срывом"),
        ("withHangsAttemptsCount", "С зависанием")) if value.get(key)]
    if weighted:
        lines.append(" · ".join(weighted))
    belays = [f"{label} {value[key]}" for key, label in (
        ("leadAttemptsCount", "нижняя"), ("topRopeAttemptsCount", "верхняя"),
        ("autoBelayAttemptsCount", "авто"), ("boulderingAttemptsCount", "боулдеринг"),
        ("unknownBelayAttemptsCount", "не указана")) if value.get(key)]
    if belays:
        lines.append("Страховка, попытки: " + " · ".join(belays))
    maxima = [f"{label} {value[key]}" for key, label in (
        ("maxAttemptedGrade", "пробовал"), ("maxReachedTopGrade", "дошёл"),
        ("maxCompletedGrade", "чисто")) if value.get(key)]
    if maxima:
        lines.append("Максимум: " + " · ".join(maxima))
    if "completionRate" in value:
        lines.append(f"Закрыто: {_percent(value['completionRate'])} · "
                     f"Попыток/трасса: {_number(round(value['attemptsPerRoute'], 1) if value.get('attemptsPerRoute') is not None else None)} · "
                     f"Попыток/чистая: {_number(round(value['attemptsPerCompletedRoute'], 1) if value.get('attemptsPerCompletedRoute') is not None else None)}")
    return "\n".join(lines)


def _comparison_line(dto):
    arrows = {"up": "↑", "down": "↓", "equal": "="}
    changes = dto.get("comparison") or {}
    values = [f"{label} {arrows[changes[key]]}" for key, label in (
        ("trainingsCount", "тренировки"), ("completedRoutes", "чистые"),
        ("completionRate", "доля закрытых"), ("attemptsPerCompletedRoute", "попыток/чистая"),
        ("maxCompletedGrade", "макс. чисто")) if changes.get(key) in arrows]
    return " · ".join(values)


def statistics(dto: dict) -> str:
    value = dto.get("training", dto)
    if value is None or dto.get("active") is False:
        return "Тренировка не найдена."
    labels = {"week": "📅 Неделя", "month": "🗓 Месяц", "last_training": "🕘 Последняя тренировка",
              "progress": "📈 Прогресс", "grades": "🎯 По категориям", "locations": "📍 По локациям",
              "projects": "🔄 Проекты", "records": "🏆 Рекорды"}
    lines = [labels.get(dto.get("scope"), "🧗 Текущая тренировка")]
    context = [str(x) for x in ((value.get("location") or {}).get("name"), value.get("date")) if x]
    if dto.get("dateFrom") or dto.get("dateTo"):
        context.append(f"{dto.get('dateFrom') or 'начало'} — {dto.get('dateTo') or 'сейчас'}")
    if value.get("trainingsCount") is not None:
        context.append(f"{value['trainingsCount']} тренировок")
    if value.get("durationMinutes") is not None:
        context.append(_duration(value["durationMinutes"]))
    if context:
        lines.append(" · ".join(context))
    lines.append(summary(value))
    previous = dto.get("previousPeriod")
    if previous is not None:
        lines.append(f"\nПредыдущий период: {previous.get('dateFrom', '—')} — {previous.get('dateTo', '—')}\n"
                     f"{previous.get('trainingsCount', 0)} тренировок · {_duration(previous.get('durationMinutes')) or '—'} · "
                     f"чисто {previous.get('completedRoutes', 0)} · {_percent(previous.get('completionRate'))} · "
                     f"макс. {_number(previous.get('maxCompletedGrade'))}")
    if comparison := _comparison_line(dto):
        lines.append("Изменение: " + comparison)
    grades = dto.get("grades", [])
    if grades:
        lines.append("\nПо категориям\n" + grade_table(grades))
    for row in dto.get("locations", []):
        lines.append(f"\n📍 {(row.get('location') or {}).get('name') or 'Без локации'}: "
                     f"{row.get('trainingsCount', 0)} трен. · {row.get('routesCount', 0)} трасс · "
                     f"{row.get('attemptsCount', 0)} попыток · чисто {row.get('completedRoutes', 0)} "
                     f"({_percent(row.get('completionRate'))}) · макс. {_number(row.get('maxCompletedGrade'))}")
    for row in dto.get("projects", []):
        route = row.get("route") or {}
        lines.append(f"• {route.get('name') or 'Трасса'} {route.get('grade') or ''} · "
                     f"точка {_number(row.get('highPoint'))}/{_number(row.get('totalMoves'))} · срывов {_number(row.get('falls'))}")
    periods = dto.get("periods", [])
    if periods:
        lines.append("\nМесяц | трен. | чисто/трасс | макс. чисто")
        for row in sorted(periods, key=lambda x: x['period']):
            lines.append(f"{row['period']} | {row.get('trainingsCount', 0)} | "
                         f"{row.get('completedRoutes', 0)}/{row.get('routesCount', 0)} | {_number(row.get('maxCompletedGrade'))}")
    records = dto.get("records")
    if records:
        lines.append("\nРекорды: " + " · ".join(f"{label} {_number(records.get(key))}" for key, label in (
            ("highestCompletedGrade", "чисто"), ("highestFlashGrade", "Flash"), ("highestRedpointGrade", "Red Point"))))
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
            lines.append(f"№{attempt.get('sequence', attempt.get('number', '?'))} · {title}" + (" · 🧪 тест" if attempt.get("isTest") else "") + f"\n• Дошёл до конца: {yn(attempt.get('reachedTop'))}\n"
                         f"• Пролез чисто: {yn(attempt.get('cleanAscent'))}\n"
                         f"• Стиль: {STYLE_NAMES.get(attempt.get('style', 'unknown'), 'Не указан')}\n"
                         f"• Страховка: {BELAY_NAMES.get(attempt.get('belay', 'unknown'), 'Не указана')}\n"
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

"""Incomplete AI entries stay in PostgreSQL until the seven required facts are known."""
from datetime import timedelta

from app.attempt_management import card, dialog_set
from app.jobs import now
from app.models import Location, RouteAttempt
from app.public_models import DialogState
from app.telegram_format import button, menu
from app.tool_service import _active, execute_tool

FIELDS = {"region": "Регион", "sector": "Сектор", "name": "Название трассы", "grade": "Категория",
          "clean_ascent": "Чисто: да или нет", "style": "Стиль: onsight / flash / redpoint / со срывом / с зависанием",
          "belay": "Страховка: нижняя / верхняя / автостраховка / боулдеринг"}


async def place(session, training):
    area = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    sector = next((s for s in reversed(training.sections) if area and s.location_id == area.id), None)
    return {"region": area.name if area else None, "sector": sector.name if sector else None}


async def save_or_ask(session, user, job, intent, reply):
    training = await _active(session, user.id)
    if not training or training.id != job.training_id:
        await reply(session, job, "Запись не сохранена: начните тренировку и повторите запись.", menu(bool(training)))
        return
    dialog = await session.get(DialogState, user.id)
    pending = job.payload.get("pending_attempt")
    if pending and (not valid_draft(dialog, training.id) or dialog.data.get("token") != pending.get("token") or
                    dialog.data.get("training_id") != training.id):
        await reply(session, job, "Черновик уже изменён или отменён. Повторите запись через «Записать пролаз».")
        return
    facts = dict(pending.get("facts", {})) if pending else {}
    if intent.continue_current_route and not pending:
        previous = job.payload.get("last_route") or {}
        facts.update({k: previous[k] for k in ("name", "grade", "region", "sector") if previous.get(k)})
    # Defaults from Pydantic are not evidence supplied by the user/model.
    supplied = intent.model_dump(exclude_none=True, exclude_unset=True)
    for key in (*FIELDS, "reached_top", "falls", "hangs", "attempts", "notes"):
        if key in supplied and supplied[key] not in ("", "unknown"):
            facts[key] = supplied[key]
    facts["is_test"] = bool(facts.get("is_test") or user.test_mode_enabled or intent.is_test or
                            job.payload["command"].casefold().startswith("тест"))
    defaults = await place(session, training)
    for key in ("region", "sector"):
        # A sector from another region cannot be inherited after a region change.
        if key == "sector" and facts.get("region", "").casefold() != (defaults.get("region") or "").casefold():
            continue
        if not facts.get(key) and defaults.get(key):
            facts[key] = defaults[key]
    if facts.get("falls") or facts.get("hangs") or facts.get("style") in ("with_falls", "with_hangs"):
        facts["clean_ascent"] = False
        if facts.get("falls"):
            facts["style"] = "with_falls"
        elif facts.get("hangs"):
            facts["style"] = "with_hangs"
    elif facts.get("style") in ("onsight", "flash", "redpoint"):
        facts.setdefault("clean_ascent", True)
        if facts["clean_ascent"] is False:
            facts.pop("style")  # Ask for a consistent style rather than inventing a fall/hang.
    missing = [label for key, label in FIELDS.items() if facts.get(key) is None or facts.get(key) in ("", "unknown")]
    if missing:
        await dialog_set(session, user.id, "attempt_missing", {"form": "attempt_capture", "training_id": training.id,
                         "token": job.id, "facts": facts})
        await reply(session, job, "Пролаз пока не сохранён. Уточните:\n" + "\n".join("• " + x for x in missing) +
                    "\nОтветьте текстом или голосом. /cancel — отмена.")
        return
    raw = {camel: facts[key] for key, camel in {"name": "name", "grade": "grade", "attempts": "attempts",
        "reached_top": "reachedTop", "clean_ascent": "cleanAscent", "falls": "falls", "hangs": "hangs",
        "style": "style", "belay": "belay", "notes": "notes", "is_test": "isTest"}.items() if key in facts}
    # Reuse a verified current catalogue location, preserving gym/country metadata.
    area = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    area_raw = {"id": area.id} if area and area.name.casefold() == facts["region"].casefold() else {"name": facts["region"]}
    dto = await execute_tool(session, "append_climbing_attempt", {"user": {"id": user.id},
        "date": training.local_date.isoformat(), "area": area_raw, "sector": {"name": facts["sector"]}, "attempt": raw}, job.id)
    if dialog and dialog.data.get("form") == "attempt_capture":
        await session.delete(dialog)
    saved = await session.get(RouteAttempt, dto["attemptId"])
    await reply(session, job, "Сохранено.\n" + await card(session, saved),
                [[button("✏️ Изменить", "am:pick:" + saved.id)],
                 [button("🧗 Текущая тренировка", "training:details:current")], [button("← Главное меню", "journal")]])


def valid_draft(dialog, training_id):
    return bool(dialog and dialog.data.get("form") == "attempt_capture" and
                dialog.data.get("training_id") == training_id and dialog.created_at >= now() - timedelta(minutes=30))

"""Continue an AI draft with buttons without restarting the full manual wizard."""
from app.telegram_format import button

CHOICES = {
    "belay": ("Какая страховка?", (("Нижняя", "lead"), ("Верхняя", "top_rope"),
              ("Автостраховка", "auto_belay"), ("Боулдеринг", "bouldering"))),
    "reached_top": ("Дошли до конца?", (("Да", "yes"), ("Нет", "no"))),
    "style": ("Стиль попытки?", (("Onsight", "onsight"), ("Flash", "flash"),
              ("Red Point", "redpoint"), ("Со срывом", "with_falls"),
              ("С зависанием", "with_hangs"), ("Не долез", "not_reached"), ("Не указан", "unknown"))),
    "clean_ascent": ("Пролезли чисто, без срывов и зависаний?", (("Да", "yes"), ("Нет", "no"))),
}


async def advance(session, user, job, training, facts, reply):
    from app.attempt_capture import complete_facts, place
    from app.attempt_management import dialog_set
    # Normalize drafts already inside the old wizard, preserving its answers.
    for old, new in (("reachedTop", "reached_top"), ("cleanAscent", "clean_ascent")):
        if old in facts:
            facts[new] = facts.pop(old)
    from app.attempt_outcome import infer_facts
    infer_facts(facts)
    for field, (prompt, choices) in CHOICES.items():
        if field != "belay":
            continue
        value = facts.get(field)
        if value is not None and value != "" and (value != "unknown" or (field == "style" and facts.get("manual"))):
            continue
        await dialog_set(session, user.id, field, {**facts, "form": "catalog_manual", "training_id": training.id})
        await reply(session, job, prompt, [[button(label, "form:" + value)] for label, value in choices])
        return
    facts["manual"] = True
    defaults = await place(session, training)
    for key in ("region", "sector"):
        if not facts.get(key) and defaults.get(key):
            facts[key] = defaults[key]
    await complete_facts(session, user, job, training, facts, reply)


async def answer(session, user, job, training, dialog, reply):
    facts = {k: v for k, v in dialog.data.items() if k not in ("form", "training_id")}
    from app.attempt_capture import clear_inferred
    clear_inferred(facts)
    field = {"top": "reached_top", "clean": "clean_ascent"}.get(dialog.state, dialog.state)
    # Old forms may already be at optional counters. Do not ask them again.
    if field in ("falls", "hangs"):
        command = job.payload["command"]
        if not command.isdigit() or int(command) > 1000:
            await reply(session, job, "Введите число от 0 до 1000.")
            return
        facts[field] = int(command)
    elif field in CHOICES:
        value = job.payload["command"].removeprefix("form:")
        if value not in {item[1] for item in CHOICES[field][1]}:
            await advance(session, user, job, training, facts, reply)
            return
        facts[field] = value == "yes" if field in ("reached_top", "clean_ascent") else value
        if field == "style" and value == "not_reached":
            facts.pop("reached_top", None)
            facts.pop("clean_ascent", None)
        if field == "style" and value == "unknown":
            facts["manual"] = True
    await advance(session, user, job, training, facts, reply)

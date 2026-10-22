"""Deterministic catalogue choices bound to one user's current attempt draft."""
import secrets

from app.attempt_management import dialog_set
from app.catalog_search import search, target, remember
from app.models import Location, Section
from app.public_models import DialogState
from app.telegram_format import button, menu
from app.tool_service import _active

LEVELS = (("region", "locations", "location_id"), ("sector", "sections", "section_id"), ("name", "routes", "route_id"))
LABELS = {"region": "район", "sector": "сектор", "name": "трассу"}


def reset_from(facts, field):
    index = [x[0] for x in LEVELS].index(field)
    for name, _, key in LEVELS[index:]:
        facts.pop(key, None)
        facts.pop("create_"+name, None)
    facts.pop("grade_confirmed", None)


async def choose(session, user, job, training, facts, field, kind, query, parent, reply, offset=0):
    result = await search(session, user.id, kind, query, parent, offset)
    token = secrets.token_hex(4)
    selection = {"token": token, "field": field, "kind": kind, "query": query, "parent": parent,
                 "ids": [x["id"] for x in result["items"]]}
    await dialog_set(session, user.id, "catalog_choice", {"form": "attempt_capture", "training_id": training.id,
        "token": job.id, "facts": facts, "selection": selection})
    keyboard = []
    for i, item in enumerate(result["items"]):
        names = list(dict.fromkeys(x for x in (item.get("name_en"), item.get("name_native"), item["name"]) if x))
        suffix = (" · "+item["grade"]) if item["grade"] else (" · "+item["country"]) if item["country"] else ""
        if item.get("section"):
            suffix += " · "+item["section"]
        if kind != "locations":
            suffix += " · "+item["location"]
        elif item["visibility"]:
            suffix += " · "+("общий" if item["visibility"] == "public" else "личный")
        keyboard.append([button((" / ".join(names)+suffix)[:120], f"cs:{token}:{i}")])
    if result["next_offset"] is not None:
        keyboard.append([button("Далее", f"cp:{token}:{result['next_offset']}")])
    if offset:
        keyboard.append([button("В начало", f"cp:{token}:0")])
    if query:
        keyboard.append([button("📚 Посмотреть каталог", f"cb:{token}")])
        if field == "region":
            keyboard.extend([[button("➕ Создать свой район", f"cn:{token}:outdoor")],
                             [button("➕ Создать скалодром", f"cn:{token}:gym")]])
        else:
            keyboard.append([button("➕ Создать свою запись", f"cn:{token}")])
    keyboard.append([button("Отмена", "/cancel")])
    await reply(session, job, f"Выберите {LABELS[field]} из БД" + (f" для «{query}»" if query else "") +
        (". Совпадений не найдено." if not result["items"] else ".") +
        "\nМожно написать другое название для поиска. Новая запись создаётся только в личном каталоге.", keyboard)


def grade_key(value):
    from app.grades import normalize_grade
    return normalize_grade(value) or ""


async def resolve(session, user, job, training, facts, reply, browse=False):
    # A training's location is context, never a boundary for finding an ascent.
    if not facts.get("place_only"):
        if facts.get("route_id"):
            await route_place(session, user.id, facts)
        elif facts.get("name") and not facts.get("create_name"):
            matches = (await search(session, user.id, "routes", facts["name"]))["items"]
            exact = [item for item in matches if item["match"] == "exact"]
            if len(exact) == 1:
                facts["route_id"] = exact[0]["id"]
                await route_place(session, user.id, facts)
            elif matches:
                await choose(session, user, job, training, facts, "name", "routes", facts["name"], None, reply)
                return False
    parent = None
    for field, kind, key in LEVELS:
        if field == "name" and facts.get("place_only"):
            return True
        if facts.get("create_"+field):
            parent = None
            continue
        if facts.get(key):
            item = await target(session, user.id, kind, facts[key])
            actual_parent = getattr(item, "location_id", None) or getattr(item, "section_id", None)
            if kind != "locations" and (not parent or actual_parent != parent):
                reset_from(facts, field)
            else:
                facts[field] = item.name
                parent = item.id
                continue
        value = facts.get(field)
        if not value and not browse:
            return True
        # A newly approved parent does not exist in PostgreSQL yet.
        prior_new = field != "region" and not parent
        matches = [] if prior_new else (await search(session, user.id, kind, value or "", parent))["items"]
        exact = [x for x in matches if x["match"] == "exact"]
        if value and len(exact) == 1:
            facts[key], facts[field] = exact[0]["id"], exact[0]["name"]
            parent = exact[0]["id"]
        else:
            if prior_new:
                # No unrelated sectors/routes are offered across parent boundaries.
                await new_child(session, user, job, training, facts, field, kind, value, reply)
            else:
                await choose(session, user, job, training, facts, field, kind, value or "", parent, reply)
            return False
    if facts.get("route_id"):
        route = await target(session, user.id, "routes", facts["route_id"])
        if route.grade and facts.get("grade") and grade_key(route.grade) != grade_key(facts["grade"]) and not facts.get("grade_confirmed"):
            token = secrets.token_hex(4)
            await dialog_set(session, user.id, "catalog_choice", {"form":"attempt_capture", "training_id":training.id,
                "token":job.id, "facts":facts, "selection":{"token":token,"field":"grade","db_grade":route.grade}})
            await reply(session, job, f"У трассы «{route.name}» в БД категория {route.grade}, в сообщении — {facts['grade']}. Какую сохранить в пролазе?",
                [[button("Из БД: "+route.grade, f"cg:{token}:db")], [button("Мою: "+facts['grade'], f"cg:{token}:user")],
                 [button("Отмена", "/cancel")]])
            return False
        if route.grade and not facts.get("grade"):
            facts["grade"] = route.grade
    return True


async def route_place(session, uid, facts):
    """Use the selected route's real hierarchy only for this ascent."""
    route = await target(session, uid, "routes", facts["route_id"])
    section = await target(session, uid, "sections", route.section_id)
    area = await target(session, uid, "locations", section.location_id)
    for field in ("region", "sector", "name"):
        facts.pop("create_"+field, None)
    facts.update(name=route.name, sector=section.name, region=area.name,
                 section_id=section.id, location_id=area.id)


async def new_child(session, user, job, training, facts, field, kind, value, reply):
    token = secrets.token_hex(4)
    await dialog_set(session, user.id, "catalog_choice", {"form":"attempt_capture", "training_id":training.id,
        "token":job.id, "facts":facts, "selection":{"token":token,"field":field,"kind":kind,"query":value or "","ids":[]}})
    await reply(session, job, f"Укажите {LABELS[field]} для новой личной записи." if not value else
        f"Создать в личном каталоге {LABELS[field]} «{value}»?",
        ([[button("➕ Создать свою запись", f"cn:{token}")]] if value else [])+[[button("Отмена", "/cancel")]])


async def handle(session, user, job, reply):
    from app.attempt_capture import valid_draft, complete_facts
    command = job.payload["command"]
    dialog = await session.get(DialogState, user.id)
    callback = command.startswith(("cs:", "cn:", "cp:", "cb:", "cg:"))
    opening = command in ("catalog:choose", "training:location")
    selection = dialog.data.get("selection", {}) if dialog else {}
    editing = dialog and dialog.state == "catalog_choice" and job.lane == "fast" and not command.startswith((
        "/", "stats:", "training:", "attempt:", "am:", "tr:", "trainings:", "trainings-test:", "test:", "gear:", "catalog:", "rs:")) and command not in ("journal", "profile")
    if not (callback or opening or editing or command == "catalog:manual"):
        return False
    training = await _active(session, user.id)
    if not training or (not opening and not valid_draft(dialog, training.id)):
        await reply(session, job, "Выбор устарел. Откройте текущую тренировку заново.", menu(bool(training)))
        return True
    if opening:
        facts = dict(dialog.data.get("facts", {})) if command == "catalog:choose" and valid_draft(dialog, training.id) else {}
        if command == "training:location":
            facts["place_only"] = True
        else:
            await choose(session, user, job, training, facts, "name", "routes", "", None, reply)
            return True
        await complete_facts(session, user, job, training, facts, reply, browse=True)
        return True
    if command == "catalog:manual" and valid_draft(dialog, training.id):
        data = dict(dialog.data["facts"])
        data.update(training_id=training.id, form="catalog_manual")
        state = "belay" if data.get("grade") else "grade"
        await dialog_set(session, user.id, state, data)
        await reply(session, job, "Какая страховка?" if state == "belay" else "Введите категорию, например 6B.",
            [[button("Нижняя", "form:lead"), button("Верхняя", "form:top_rope")],
             [button("Автостраховка", "form:auto_belay"), button("Боулдеринг", "form:bouldering")]] if state == "belay" else None)
        return True
    facts = dict(dialog.data["facts"])
    if callback and command.split(":")[1] != selection.get("token"):
        await reply(session, job, "Кнопка устарела. Используйте последний список вариантов.")
        return True
    field = selection.get("field")
    if command.startswith("cg:"):
        if field != "grade" or command.split(":")[-1] not in ("db", "user"):
            return True
        if command.endswith(":db"):
            facts["grade"] = selection["db_grade"]
        facts["grade_confirmed"] = True
    elif field == "grade":
        await reply(session, job, "Выберите категорию кнопкой или отмените ввод через /cancel.")
        return True
    elif command.startswith("cs:"):
        parts = command.split(":")
        if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) >= len(selection.get("ids", [])):
            return True
        item_id = selection["ids"][int(parts[2])]
        item = await target(session, user.id, selection["kind"], item_id)
        key = next(x[2] for x in LEVELS if x[0] == field)
        reset_from(facts, field)
        facts[field], facts[key] = item.name, item.id
        # Broad metadata queries (e.g. a grade or country) must not become name aliases.
        # Remember an explicit spelling only when it resembles a name of this item.
        from sqlalchemy import select, func, or_
        names = [item.name, getattr(item, "name_en", None), getattr(item, "name_native", None)]
        resembles_name = selection.get("query") and await session.scalar(select(or_(*(
            func.catalog_translit(name).op("OPERATOR(public.%)")(func.catalog_translit(selection["query"]))
            for name in names if name))))
        if resembles_name:
            await remember(session, user.id, selection["kind"], item.id, selection["query"])
    elif command.startswith("cn:"):
        if not selection.get("query"):
            return True
        reset_from(facts, field)
        facts[field], facts["create_"+field] = selection["query"], True
        if field == "region":
            facts["location_type"] = "gym" if command.endswith(":gym") else "outdoor"
    else:
        if command.startswith("cp:"):
            page = command.split(":")[-1]
            if not page.isdigit() or int(page) > 10000:
                return True
            offset, query = int(page), selection["query"]
        else:
            offset, query = 0, "" if command.startswith("cb:") else command.strip()
        if not query and not callback:
            return True
        if selection.get("parent") or field == "region" or selection.get("kind") == "routes":
            await choose(session, user, job, training, facts, field, selection["kind"], query, selection.get("parent"), reply, offset)
        else:
            await new_child(session, user, job, training, facts, field, selection["kind"], query, reply)
        return True
    await complete_facts(session, user, job, training, facts, reply, browse=True)
    return True


async def private_hierarchy(session, uid, facts, training):
    """Approved missing children of public catalogue entries live in an owned copy."""
    from sqlalchemy import select, func
    area = await session.get(Location, facts["location_id"]) if facts.get("location_id") else None
    needs_private = any(facts.get("create_"+field) for field in ("region", "sector", "name"))
    if needs_private and (not area or area.visibility == "public"):
        source_section = await session.get(Section, facts["section_id"]) if facts.get("section_id") else None
        country = area.country if area else None
        private = await session.scalar(select(Location).where(Location.owner_id == uid, Location.visibility == "private",
            func.catalog_normalize(Location.name) == func.catalog_normalize(facts["region"]),
            func.coalesce(Location.country, "") == (country or "")))
        if not private:
            private = Location(owner_id=uid, visibility="private", name=facts["region"], country=country,
                region=area.region if area else None, type=area.type if area else facts.get("location_type", "outdoor"))
            session.add(private)
            await session.flush()
        area = private
        facts["location_id"] = area.id
        facts.pop("section_id", None)
        if source_section:
            facts["sector_name_en"] = source_section.name_en
            facts["sector_name_native"] = source_section.name_native
    if needs_private and not facts.get("section_id"):
        section = await session.scalar(select(Section).where(Section.location_id == area.id,
            func.catalog_normalize(Section.name) == func.catalog_normalize(facts["sector"])))
        if not section:
            section = Section(location_id=area.id, type="wall" if area.type=="gym" else "sector", name=facts["sector"],
                              name_en=facts.get("sector_name_en"), name_native=facts.get("sector_name_native"))
            session.add(section)
            await session.flush()
        facts["section_id"] = section.id

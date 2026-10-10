"""Small deterministic attempt wizard, usable while the AI provider is unavailable."""
import re
from datetime import timedelta

from app.jobs import now
from app.public_models import DialogState
from app.telegram_format import button, menu
from app.tool_service import _active, execute_tool
from app.schemas import ProfileUpdate
from pydantic import ValidationError


async def handle(session, user, job, reply) -> bool:
    command = job.payload["command"]
    dialog = await session.get(DialogState, user.id)
    if command in ("profile:timezone", "profile:name", "gear:form"):
        if dialog:
            await session.delete(dialog)
            await session.flush()
        if command == "gear:form":
            session.add(DialogState(user_id=user.id, state="gear_type", data={"form": "gear"}))
            await reply(session, job, "Тип снаряжения?", [[button("Скальники", "form:shoes"), button("Обвязка", "form:harness")],
                         [button("Верёвка", "form:rope"), button("Страховочное устройство", "form:belay_device")],
                         [button("Шлем", "form:helmet"), button("Магнезия", "form:chalk"), button("Другое", "form:other")]])
        else:
            field = command.split(":")[1]
            session.add(DialogState(user_id=user.id, state="profile", data={"form": "profile", "field": field}))
            await reply(session, job, "Введите часовой пояс IANA, например Europe/Moscow. /cancel — отмена." if field == "timezone" else "Введите имя. /cancel — отмена.")
        return True
    if command == "training:location":
        active = await _active(session, user.id)
        if not active:
            await reply(session, job, "Сначала начните тренировку.", menu(False))
            return True
        if dialog:
            await session.delete(dialog)
            await session.flush()
        session.add(DialogState(user_id=user.id, state="location_type", data={"form": "location", "training_id": active.id}))
        await reply(session, job, "Где тренируетесь?", [[button("Скалодром", "form:gym"), button("Скалы", "form:outdoor")]])
        return True
    if command == "attempt:form":
        active = await _active(session, user.id)
        if not active:
            await reply(session, job, "Сначала начните тренировку.", menu(False))
            return True
        if dialog:
            await session.delete(dialog)
            await session.flush()
        session.add(DialogState(user_id=user.id, state="name", data={"training_id": active.id}))
        await reply(session, job, "Введите название трассы. /cancel — отменить форму.")
        return True
    if not dialog:
        return False
    if command == "/cancel" or dialog.created_at < now()-timedelta(minutes=30):
        await session.delete(dialog)
        await reply(session, job, "Форма отменена.", menu(bool(await _active(session, user.id))))
        return True
    if command.startswith(("stats:", "training:", "profile", "gear:", "journal", "test:", "/")):
        return False
    if dialog.data.get("form") == "profile":
        try:
            changes = ProfileUpdate.model_validate({dialog.data["field"]: command}).model_dump(exclude_unset=True)
        except ValidationError:
            await reply(session, job, "Не удалось принять значение. Проверьте имя или часовой пояс и повторите.")
            return True
        for key, value in changes.items():
            setattr(user, key, value)
        await session.delete(dialog)
        await reply(session, job, "Профиль обновлён.", menu(bool(await _active(session, user.id))))
        return True
    if dialog.data.get("form") == "gear":
        data = dict(dialog.data)
        steps = {"gear_type": "type", "gear_brand": "brand", "gear_model": "model", "gear_size": "size", "gear_notes": "notes"}
        field = steps[dialog.state]
        value = command.removeprefix("form:") if field == "type" else None if command == "-" else command
        if field == "type" and value not in ("shoes", "rope", "harness", "belay_device", "helmet", "chalk", "other"):
            return True
        if value and len(value) > (1000 if field == "notes" else 50 if field == "size" else 100):
            await reply(session, job, "Значение слишком длинное. Повторите ввод.")
            return True
        data[field] = value
        if field == "notes":
            await execute_tool(session, "upsert_climbing_gear", {"user": {"id": user.id}, "gear": {k: v for k, v in data.items() if k != "form"}}, job.id)
            await session.delete(dialog)
            await reply(session, job, "Снаряжение сохранено.", menu(bool(await _active(session, user.id))))
        else:
            next_state, prompt = {"type": ("gear_brand", "Введите бренд, либо «-»."), "brand": ("gear_model", "Введите модель, либо «-»."),
                                  "model": ("gear_size", "Введите размер, либо «-»."), "size": ("gear_notes", "Введите заметку, либо «-».")}[field]
            dialog.state, dialog.data = next_state, data
            await reply(session, job, prompt)
        return True
    active = await _active(session, user.id)
    if not active or active.id != dialog.data["training_id"]:
        await session.delete(dialog)
        await reply(session, job, "Исходная тренировка завершена. Запись не сохранена.", menu(bool(active)))
        return True
    data = dict(dialog.data)
    if data.get("form") == "location":
        if dialog.state == "location_type":
            if command not in ("form:gym", "form:outdoor"):
                return True
            data["type"], dialog.state = command.removeprefix("form:"), "location_name"
            await reply(session, job, "Введите название скалодрома или района скал.")
        elif dialog.state == "location_name":
            if not command or len(command) > 200:
                await reply(session, job, "Введите название до 200 символов.")
                return True
            data["name"], dialog.state = command, "location_country"
            await reply(session, job, "Введите страну, либо «-», если не хотите указывать.")
        elif dialog.state == "location_country":
            if not command or len(command) > 200:
                await reply(session, job, "Введите страну до 200 символов.")
                return True
            data["country"], dialog.state = None if command == "-" else command, "location_section"
            await reply(session, job, "Введите сектор/зал, либо «-», чтобы пропустить.")
        elif dialog.state == "location_section":
            if not command or len(command) > 200:
                await reply(session, job, "Введите сектор до 200 символов.")
                return True
            payload = {"user": {"id": user.id}, "trainingId": active.id,
                       "area": {k: data[k] for k in ("name", "type", "country")}}
            if command != "-":
                payload["sector"] = {"name": command}
            await execute_tool(session, "update_climbing_training", payload, job.id)
            await session.delete(dialog)
            await reply(session, job, "Место тренировки сохранено в вашем каталоге.", menu(True))
            return True
        dialog.data = data
        return True
    if dialog.state == "name":
        if not command or len(command) > 200:
            await reply(session, job, "Введите название до 200 символов.")
            return True
        data["name"], dialog.state = command, "grade"
        await reply(session, job, "Введите категорию, например 6B или 6B/6B+.")
    elif dialog.state == "grade":
        if not re.fullmatch(r"[1-9][ABCabc]?\+?(?:/[1-9][ABCabc]?\+?)?", command):
            await reply(session, job, "Не распознал категорию. Пример: 6B/6B+.")
            return True
        data["grade"], dialog.state = command.upper(), "belay"
        await reply(session, job, "Какая страховка?", [[button("Нижняя", "form:lead"), button("Верхняя", "form:top_rope")],
                        [button("Автостраховка", "form:auto_belay"), button("Боулдеринг", "form:bouldering")]])
    elif dialog.state == "belay":
        value = command.removeprefix("form:")
        if value not in ("lead", "top_rope", "auto_belay", "bouldering"):
            return True
        data["belay"], dialog.state = value, "top"
        await reply(session, job, "Дошли до конца?", [[button("Да", "form:yes"), button("Нет", "form:no")]])
    elif dialog.state == "top":
        if command not in ("form:yes", "form:no"):
            return True
        data["reachedTop"], dialog.state = command == "form:yes", "style"
        await reply(session, job, "Стиль попытки?", [[button("Onsight", "form:onsight"), button("Flash", "form:flash")],
                       [button("Red Point", "form:redpoint"), button("Не указан", "form:unknown")]])
    elif dialog.state == "style":
        value = command.removeprefix("form:")
        if value not in ("onsight", "flash", "redpoint", "unknown"):
            return True
        data["style"], dialog.state = value, "clean"
        await reply(session, job, "Пролезли чисто, без срывов и зависаний?", [[button("Да", "form:yes"), button("Нет", "form:no")]])
    elif dialog.state == "clean":
        if command not in ("form:yes", "form:no"):
            return True
        data["cleanAscent"], dialog.state = command == "form:yes", "falls"
        await reply(session, job, "Сколько было срывов? Введите число, 0 если не было.")
    elif dialog.state == "falls":
        if not command.isdigit() or int(command) > 1000:
            await reply(session, job, "Введите число срывов от 0 до 1000.")
            return True
        data["falls"], dialog.state = int(command), "hangs"
        await reply(session, job, "Сколько было зависаний? Введите число, 0 если не было.")
    elif dialog.state == "hangs":
        if not command.isdigit() or int(command) > 1000:
            await reply(session, job, "Введите число зависаний от 0 до 1000.")
            return True
        data["hangs"] = int(command)
        if not data["reachedTop"]:
            data["cleanAscent"] = False
        payload = {k: v for k, v in data.items() if k != "training_id"}
        await execute_tool(session, "append_climbing_attempt", {"user": {"id": user.id}, "date": active.local_date.isoformat(), "attempt": payload}, job.id)
        await session.delete(dialog)
        await reply(session, job, "Попытка сохранена.", menu(True))
        return True
    dialog.data = data
    return True

"""Owned, versioned attempt mutations shared by Telegram and the public API."""
import hashlib
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.attempt_outcome import outcome, normalized_style
from app.models import Location, Section, RouteAttempt, TrainingSession, User
from app.public_models import DialogState
from app.public_schemas import AttemptChanges
from app.telegram_format import button, menu, ascent_card, STYLE_NAMES, BELAY_NAMES
from app.jobs import now


async def training_for(session, uid, scope):
    query = select(TrainingSession).where(TrainingSession.user_id == uid,
        TrainingSession.status == ("active" if scope == "current" else "completed"))
    return await session.scalar(query.order_by(TrainingSession.local_date.desc(),
        TrainingSession.created_at.desc(), TrainingSession.id.desc()).limit(1))


async def rows(session, uid, tid):
    return list((await session.scalars(select(RouteAttempt).join(TrainingSession).where(
        TrainingSession.user_id == uid, TrainingSession.id == tid).order_by(RouteAttempt.sequence).limit(1001))).all())


async def locked_training(session, uid, tid, version):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    training = await session.scalar(select(TrainingSession).where(
        TrainingSession.user_id == uid, TrainingSession.id == tid).with_for_update())
    if not training:
        raise HTTPException(404, "Training not found")
    if training.version != version:
        raise HTTPException(409, "Training changed; select attempts again")
    return training


async def patch_rows(session, uid, tid, version, ids, changes):
    training = await locked_training(session, uid, tid, version)
    values = changes.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "Specify changed fields")
    for field in ("name", "grade", "style", "belay", "is_test"):
        if field in values and values[field] is None:
            raise HTTPException(422, f"{field} cannot be null")
    selected = [x for x in await rows(session, uid, tid) if x.id in ids]
    if len(selected) != len(set(ids)):
        raise HTTPException(404, "Attempt not found")
    raw = dict(values)
    for snake, camel in (("reached_top", "reachedTop"), ("clean_ascent", "cleanAscent"), ("is_test", "isTest")):
        if snake in raw:
            raw[camel] = raw.pop(snake)
    for item in selected:
        facts, style = outcome(raw, item), normalized_style(raw, item)
        for field, value in facts.items():
            setattr(item, field, value)
        item.style = style
        for field in ("falls", "hangs", "belay", "notes", "is_test"):
            if field in values:
                setattr(item, field, values[field])
        if "name" in values or "grade" in values:
            snapshot = {**(item.route_snapshot or {})}
            for field in ("name", "grade"):
                if field in values:
                    snapshot[field] = values[field]
            if snapshot != item.route_snapshot:
                key = f"{tid}:{item.route_session_key or item.id}:{snapshot.get('name')}:{snapshot.get('grade')}"
                item.route_session_key = "route_session_"+hashlib.sha256(key.encode()).hexdigest()[:32]
                item.route_id = None
                item.route_snapshot = snapshot
    training.version += 1
    await session.flush()
    return selected, training.version


async def delete_rows(session, uid, tid, version, ids):
    training = await locked_training(session, uid, tid, version)
    if training.status != "active":
        raise HTTPException(409, "Only current training attempts can be deleted")
    selected = [x for x in await rows(session, uid, tid) if x.id in ids]
    if len(selected) != len(set(ids)):
        raise HTTPException(404, "Attempt not found")
    for item in selected:
        await session.delete(item)
    training.version += 1
    await session.flush()
    return len(selected), training.version


async def card(session, item):
    training = await session.get(TrainingSession, item.training_id)
    snapshot = item.route_snapshot or {}
    region = await session.get(Location, snapshot.get("areaId") or training.primary_location_id) if snapshot.get("areaId") or training.primary_location_id else None
    sector = await session.get(Section, snapshot["sectorId"]) if snapshot.get("sectorId") else None
    return ascent_card(item, region.name if region else None, sector.name if sector else None)


async def dialog_set(session, uid, state, data):
    existing = await session.get(DialogState, uid)
    if existing:
        await session.delete(existing)
        await session.flush()
    dialog = DialogState(user_id=uid, state=state, data=data)
    session.add(dialog)
    return dialog


async def confirm_delete(session, uid, job, training, selected, reply):
    if not selected:
        await reply(session, job, "Сначала выберите попытки для удаления.")
        return
    await dialog_set(session, uid, "attempt_delete", {"form": "attempt_manage", "training_id": training.id,
        "version": training.version, "ids": [x.id for x in selected]})
    preview = "\n".join(f"№{x.sequence} · {(x.route_snapshot or {}).get('name')} {(x.route_snapshot or {}).get('grade')}" for x in selected[:20])
    await reply(session, job, f"Удалить {len(selected)} попыток текущей тренировки?\n{preview}",
        [[button("🗑 Подтверждаю удаление", "am:delete")], [button("Отмена", "am:cancel")]])


async def apply_intent(session, user, job, intent, reply):
    if intent.changes:
        intent.changes = AttemptChanges.model_validate(intent.changes.model_dump(exclude_none=True, exclude_unset=True))
    if intent.kind == "delete_attempts" and intent.training_scope != "current":
        await reply(session, job, "Удалять можно только попытки текущей тренировки. Завершённая тренировка не изменена.")
        return
    scope = "current" if intent.kind == "delete_attempts" else intent.training_scope
    anchor = {"id": job.training_id, "version": job.expected_version} if scope == "current" else job.payload.get("last_training")
    if not anchor or not anchor.get("id"):
        await reply(session, job, "Нужная тренировка не найдена.", menu(bool(await training_for(session, user.id, "current"))))
        return
    training = await locked_training(session, user.id, anchor["id"], anchor["version"])
    all_rows = await rows(session, user.id, training.id)
    if len(all_rows) > 1000:
        raise HTTPException(422, "Select a smaller training")
    selectors = sum(bool(x) for x in (intent.target_all, intent.target_last, intent.target_numbers, intent.target_name))
    if selectors != 1:
        await reply(session, job, "Укажите номера попыток, точное название трассы, последнюю попытку или явно «все пролазы».")
        return
    selected = all_rows if intent.target_all else all_rows[-1:] if intent.target_last else [x for x in all_rows if
        x.sequence in intent.target_numbers] if intent.target_numbers else [x for x in all_rows if
        str((x.route_snapshot or {}).get("name", "")).casefold() == intent.target_name.casefold()]
    if not selected or (intent.target_numbers and len(selected) != len(set(intent.target_numbers))) or (intent.target_name and len(selected) != 1):
        await reply(session, job, "Не удалось однозначно выбрать попытки. Укажите номера из списка пролазов.")
        return
    if intent.kind == "delete_attempts":
        await confirm_delete(session, user.id, job, training, selected, reply)
    elif not intent.changes or not intent.changes.model_dump(exclude_unset=True):
        await reply(session, job, "Укажите, какие характеристики изменить. Остальные поля сохраняются.")
    else:
        changed, _ = await patch_rows(session, user.id, training.id, training.version,
                                      [x.id for x in selected], intent.changes)
        await reply(session, job, f"Изменено попыток: {len(changed)}" + ("\n"+await card(session, changed[0]) if len(changed)==1 else ""), menu(bool(await training_for(session,user.id,"current"))))


async def handle(session, user, job, reply):
    command = job.payload["command"]
    if job.lane == "ai":
        return False
    dialog = await session.get(DialogState, user.id)
    if command.startswith("attempts:"):
        _, scope, offset = command.split(":")
        if scope not in ("current", "last") or not offset.isdigit():
            raise HTTPException(422, "Invalid list")
        training = await training_for(session, user.id, scope)
        if not training:
            await reply(session, job, "Тренировка не найдена.")
            return True
        values = await rows(session,user.id,training.id)
        start = int(offset)
        keyboard = [[button(f"№{x.sequence} · {(x.route_snapshot or {}).get('name')}"[:60], "am:pick:"+x.id)] for x in values[start:start+15]]
        if start+15 < len(values): keyboard.append([button("Далее", f"attempts:{scope}:{start+15}")])
        if start: keyboard.append([button("Назад", f"attempts:{scope}:{max(0,start-15)}")])
        if scope == "current": keyboard.append([button("🗑 Выбрать несколько для удаления", "am:select")])
        keyboard.append([button("← Журнал", "journal")])
        await reply(session, job, "Выберите попытку для редактирования"+ (" или удаления." if scope=="current" else "."), keyboard)
        return True
    if command.startswith("am:pick:"):
        item = await session.scalar(select(RouteAttempt).join(TrainingSession).where(
            RouteAttempt.id == command.removeprefix("am:pick:"), TrainingSession.user_id==user.id))
        if not item: raise HTTPException(404,"Attempt not found")
        training = await session.get(TrainingSession,item.training_id)
        await dialog_set(session,user.id,"attempt_edit",{"form":"attempt_manage","training_id":training.id,
            "version":training.version,"ids":[item.id]})
        keyboard = [[button(label,"am:field:"+field)] for field,label in (
            ("name","Название"),("grade","Категория"),("clean_ascent","Чистота"),("reached_top","Дошёл до конца"),
            ("style","Стиль"),("belay","Страховка"),("falls","Срывы"),("hangs","Зависания"),("notes","Комментарий"))]
        if training.status=="active": keyboard.append([button("🗑 Удалить попытку","am:askdelete")])
        keyboard.append([button("Закрыть","am:cancel")])
        await reply(session,job,await card(session,item),keyboard)
        return True
    if command == "am:select":
        training = await training_for(session, user.id, "current")
        if not training:
            await reply(session, job, "Сначала начните тренировку.")
            return True
        dialog = await dialog_set(session, user.id, "attempt_select_delete", {"form":"attempt_manage",
            "training_id":training.id,"version":training.version,"ids":[],"offset":0})
        await selection_screen(session, user.id, job, dialog, reply)
        return True
    if not dialog or dialog.data.get("form")!="attempt_manage":
        if command.startswith("am:"):
            await reply(session,job,"Выберите попытку заново: карточка устарела.")
            return True
        return False
    if command in ("am:cancel","/cancel") or dialog.created_at < now()-timedelta(minutes=5):
        await session.delete(dialog)
        await reply(session,job,"Действие отменено.",menu(bool(await training_for(session,user.id,"current"))))
        return True
    if command.startswith(("stats:","training:","attempt:","profile","gear:","journal")) or command.startswith("/"):
        return False
    data=dialog.data
    if dialog.state == "attempt_select_delete" and command.startswith(("am:toggle:","am:page:","am:all")):
        await locked_training(session,user.id,data["training_id"],data["version"])
        values=await rows(session,user.id,data["training_id"])
        if len(values)>1000: raise HTTPException(422,"Too many attempts")
        selected=set(data["ids"])
        if command.startswith("am:toggle:"):
            aid=command.removeprefix("am:toggle:")
            if aid not in {x.id for x in values}: raise HTTPException(404,"Attempt not found")
            if aid in selected: selected.remove(aid)
            else: selected.add(aid)
        if command == "am:all": selected={x.id for x in values}
        offset=command.removeprefix("am:page:") if command.startswith("am:page:") else str(data.get("offset",0))
        if not offset.isdigit(): raise HTTPException(422,"Invalid page")
        dialog.data={**data,"ids":sorted(selected),"offset":int(offset)}
        await selection_screen(session,user.id,job,dialog,reply)
    elif command=="am:askdelete":
        training=await locked_training(session,user.id,data["training_id"],data["version"])
        selected=[x for x in await rows(session,user.id,training.id) if x.id in data["ids"]]
        await confirm_delete(session,user.id,job,training,selected,reply)
    elif command=="am:delete" and dialog.state=="attempt_delete":
        count,_=await delete_rows(session,user.id,data["training_id"],data["version"],data["ids"])
        await session.delete(dialog)
        await reply(session,job,f"Удалено попыток: {count}",menu(True))
    elif command.startswith("am:field:") and dialog.state=="attempt_edit":
        field=command.removeprefix("am:field:")
        if field not in AttemptChanges.model_fields: raise HTTPException(422,"Unknown field")
        dialog.state,dialog.data="attempt_value",{**data,"field":field}
        options=STYLE_NAMES if field=="style" else BELAY_NAMES if field=="belay" else {"yes":"Да","no":"Нет"} if field in ("clean_ascent","reached_top","is_test") else None
        await reply(session,job,"Выберите новое значение." if options else "Введите новое значение. /cancel — отмена.",
            [[button(label,"am:value:"+value)] for value,label in options.items()] if options else None)
    elif dialog.state=="attempt_value":
        field=data["field"]
        value=command.removeprefix("am:value:")
        if field in ("falls","hangs"):
            if not value.isdigit():
                await reply(session,job,"Введите число от 0 до 1000.")
                return True
            value=int(value)
        elif field in ("clean_ascent","reached_top","is_test"):
            if value not in ("yes","no"): return True
            value=value=="yes"
        from pydantic import ValidationError
        try: changes=AttemptChanges.model_validate({field:value})
        except ValidationError:
            await reply(session,job,"Не удалось принять значение. Проверьте формат и повторите ввод.")
            return True
        changed,_=await patch_rows(session,user.id,data["training_id"],data["version"],data["ids"],changes)
        await session.delete(dialog)
        await reply(session,job,"Изменения сохранены.\n"+await card(session,changed[0]),
            [[button("✏️ Ещё изменить","am:pick:"+changed[0].id)],[button("← Журнал","journal")]])
    return True


async def selection_screen(session, uid, job, dialog, reply):
    data=dialog.data
    values=await rows(session,uid,data["training_id"])
    start=data.get("offset",0)
    keyboard=[[button(("✅ " if x.id in data["ids"] else "☐ ")+f"№{x.sequence} · {(x.route_snapshot or {}).get('name')}"[:45],
                      "am:toggle:"+x.id)] for x in values[start:start+15]]
    if start+15<len(values): keyboard.append([button("Далее",f"am:page:{start+15}")])
    if start: keyboard.append([button("Назад",f"am:page:{max(0,start-15)}")])
    keyboard.extend([[button("Выбрать все","am:all")],
                     [button(f"Удалить выбранные ({len(data['ids'])})","am:askdelete")],
                     [button("Отмена","am:cancel")]])
    await reply(session,job,"Выберите попытки текущей тренировки для удаления.",keyboard)

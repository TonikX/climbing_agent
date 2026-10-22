"""Owned, versioned attempt mutations shared by Telegram and the public API."""
import hashlib
import secrets
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.attempt_outcome import outcome, normalized_style
from app.models import Location, Section, RouteAttempt, TrainingSession, User
from app.public_models import DialogState
from app.public_schemas import AttemptChanges
from app.telegram_format import button, menu, ascent_card, summary, STYLE_NAMES, BELAY_NAMES, active_training_actions
from app.jobs import now


async def training_for(session, uid, scope):
    query = select(TrainingSession).where(TrainingSession.user_id == uid,
        TrainingSession.status == ("active" if scope == "current" else "completed"))
    return await session.scalar(query.order_by(TrainingSession.local_date.desc(),
        TrainingSession.created_at.desc(), TrainingSession.id.desc()).limit(1))


async def rows(session, uid, tid, limit=1001):
    query = select(RouteAttempt).join(TrainingSession).where(
        TrainingSession.user_id == uid, TrainingSession.id == tid).order_by(RouteAttempt.sequence)
    query = query.limit(limit) if limit is not None else query.options(selectinload(RouteAttempt.route))
    return list((await session.scalars(query)).all())


async def locked_training(session, uid, tid, version):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    training = await session.scalar(select(TrainingSession).where(
        TrainingSession.user_id == uid, TrainingSession.id == tid).options(selectinload(TrainingSession.sections)).with_for_update())
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
    for field in ("name", "grade", "style", "belay", "is_test", "region", "sector"):
        if field in values and values[field] is None:
            raise HTTPException(422, f"{field} cannot be null")
    all_rows = await rows(session, uid, tid)
    selected = [x for x in all_rows if x.id in ids]
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
        if any(field in values for field in ("name", "grade", "region", "sector")):
            snapshot = {**(item.route_snapshot or {})}
            for field in ("name", "grade"):
                if field in values:
                    snapshot[field] = values[field]
            if "region" in values or "sector" in values:
                from app.tool_service import _area, _section
                area_id = snapshot.get("areaId", training.primary_location_id)
                old_area = await session.get(Location, area_id) if area_id else None
                old_sector = await session.get(Section, snapshot["sectorId"]) if snapshot.get("sectorId") else None
                if "region" not in values and not old_area:
                    raise HTTPException(422,"Specify region before sector")
                # Reuse/create an OWNED hierarchy; never rename a shared catalogue object.
                area = await _area(session,{"name":values.get("region", old_area.name if old_area else None),
                    "type":old_area.type if old_area else "outdoor","country":old_area.country if old_area and
                    ("region" not in values or values["region"].casefold()==old_area.name.casefold()) else None})
                sector_name = values.get("sector",old_sector.name if old_sector else None)
                sector = await _section(session,area,{"name":sector_name}) if sector_name else None
                snapshot.update(areaId=area.id,sectorId=sector.id if sector else None)
                if sector and sector not in training.sections:
                    training.sections.append(sector)
            if snapshot != item.route_snapshot:
                key = f"{tid}:{item.route_session_key or item.id}:{snapshot.get('name')}:{snapshot.get('grade')}:{snapshot.get('areaId')}:{snapshot.get('sectorId')}"
                item.route_session_key = "route_session_"+hashlib.sha256(key.encode()).hexdigest()[:32]
                item.route_id = None
                item.route_snapshot = snapshot
    if "region" in values and len(selected)==len(all_rows):
        area_ids={x.route_snapshot.get("areaId") for x in selected}
        if len(area_ids)==1:
            training.primary_location_id=next(iter(area_ids))
    training.version += 1
    await session.flush()
    return selected, training.version


async def delete_rows(session, uid, tid, version, ids):
    training = await locked_training(session, uid, tid, version)
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
    area_id = snapshot.get("areaId",training.primary_location_id)
    region = await session.get(Location, area_id) if area_id else None
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
    confirmation = secrets.token_hex(8)
    await dialog_set(session, uid, "attempt_delete", {"form": "attempt_manage", "training_id": training.id,
        "version": training.version, "ids": [x.id for x in selected], "confirmation": confirmation})
    preview = "\n".join(f"№{x.sequence} · {(x.route_snapshot or {}).get('name')} {(x.route_snapshot or {}).get('grade')}" for x in selected[:20])
    await reply(session, job, f"Удалить {len(selected)} попыток тренировки {training.local_date:%d.%m.%Y}?\n{preview}",
        [[button("🗑 Подтверждаю удаление", "am:delete:"+confirmation)], [button("Отмена", "am:cancel")]])


async def apply_intent(session, user, job, intent, reply):
    if intent.changes:
        intent.changes = AttemptChanges.model_validate(intent.changes.model_dump(exclude_none=True, exclude_unset=True))
    scope = intent.training_scope
    anchor = {"id": job.training_id, "version": job.expected_version} if scope == "current" else job.payload.get("last_training") if scope=="last" else job.payload.get("selected_training")
    if not anchor or not anchor.get("id"):
        await reply(session, job, "Выберите тренировку для изменения или удаления.", [[button("Выбрать тренировку","trainings:0")]])
        return
    training = await locked_training(session, user.id, anchor["id"], anchor["version"])
    all_rows = await rows(session, user.id, training.id)
    if len(all_rows) > 1000:
        raise HTTPException(422, "Select a smaller training")
    selectors = sum(bool(x) for x in (intent.target_all, intent.target_last, intent.target_numbers, intent.target_name))
    selected_ids=job.payload.get("selected_attempts",[]) if scope=="selected" else []
    if selectors == 0 and selected_ids:
        selected=[x for x in all_rows if x.id in selected_ids]
        if len(selected)!=len(set(selected_ids)): raise HTTPException(404,"Attempt not found")
    elif selectors != 1:
        await reply(session, job, "Укажите номера попыток, точное название трассы, последнюю попытку или явно «все пролазы».")
        return
    else:
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
        changed, version = await patch_rows(session, user.id, training.id, training.version,
                                      [x.id for x in selected], intent.changes)
        await dialog_set(session,user.id,"training_selected",{"form":"attempt_manage","training_id":training.id,
            "version":version,"ids":[x.id for x in changed] if len(changed)==1 else []})
        await reply(session, job, f"Изменено попыток: {len(changed)}" + ("\n"+await card(session, changed[0]) if len(changed)==1 else ""), menu(bool(await training_for(session,user.id,"current"))))


async def handle(session, user, job, reply):
    command = job.payload["command"]
    if job.lane == "ai":
        return False
    dialog = await session.get(DialogState, user.id)
    if command.startswith("td:"):
        parts = command.split(":")
        if len(parts) != 3 or not parts[2].isdigit():
            raise HTTPException(422, "Invalid training version")
        _, tid, version = parts
        training = await locked_training(session, user.id, tid, int(version))
        await dialog_set(session, user.id, "training_date", {"form":"training_date", "training_id":tid,
            "version":training.version})
        await reply(session, job, f"Текущая дата: {training.local_date:%d.%m.%Y}.\nВведите новую дату: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.",
                    [[button("Отмена", "tr:"+tid)]])
        return True
    if dialog and dialog.data.get("form") == "training_date" and (command == "/cancel" or
            (not command.startswith("/") and ":" not in command and command not in ("journal", "profile"))):
        tid = dialog.data["training_id"]
        if command == "/cancel" or dialog.created_at < now()-timedelta(minutes=5):
            await session.delete(dialog)
            await reply(session, job, "Изменение даты отменено.", [[button("← Тренировка", "tr:"+tid)]])
            return True
        try:
            value = command.strip()
            new_date = datetime.strptime(value, "%d.%m.%Y").date() if "." in value else date.fromisoformat(value)
        except ValueError:
            await reply(session, job, "Некорректная дата. Введите ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.",
                        [[button("Отмена", "tr:"+tid)]])
            return True
        training = await locked_training(session, user.id, tid, dialog.data["version"])
        training.local_date = new_date
        training.version += 1
        await dialog_set(session, user.id, "training_selected", {"form":"attempt_manage", "training_id":tid,
            "version":training.version, "ids":[]})
        await reply(session, job, f"Дата тренировки изменена: {new_date:%d.%m.%Y}.",
                    [[button("🧗 Текущая тренировка", "training:details:current")],
                     *active_training_actions(training)] if training.status == "active" else
                    [[button("← Тренировка", "tr:"+tid)]])
        return True
    if command.startswith(("trainings:", "trainings-test:")):
        include_test = command.startswith("trainings-test:")
        prefix = "trainings-test:" if include_test else "trainings:"
        cursor=command.removeprefix(prefix)
        query=select(TrainingSession).where(TrainingSession.user_id==user.id)
        if not include_test:
            from app.training_visibility import not_test_only
            query = query.where(not_test_only())
        if cursor!="0":
            anchor=await session.scalar(select(TrainingSession).where(TrainingSession.user_id==user.id,TrainingSession.id==cursor))
            if not anchor: raise HTTPException(404,"Training not found")
            from sqlalchemy import tuple_
            query=query.where(tuple_(TrainingSession.local_date,TrainingSession.created_at,TrainingSession.id)<
                              (anchor.local_date,anchor.created_at,anchor.id))
        trainings=list((await session.scalars(query.options(selectinload(TrainingSession.sections)).order_by(TrainingSession.local_date.desc(),
            TrainingSession.created_at.desc(),TrainingSession.id.desc()).limit(11))).all())
        await dialog_set(session,user.id,"training_choose",{"form":"attempt_manage"})
        sector_names = {}
        sector_query = select(RouteAttempt.training_id, Section.name).join(Section,
            Section.id == RouteAttempt.route_snapshot["sectorId"].astext).where(
                RouteAttempt.training_id.in_([training.id for training in trainings[:10]]))
        if not include_test:
            sector_query = sector_query.where(RouteAttempt.is_test.is_(False))
        for tid, name in (await session.execute(sector_query.distinct().order_by(Section.name))).all():
            sector_names.setdefault(tid, []).append(name)
        keyboard=[]
        for training in trainings[:10]:
            region=await session.get(Location,training.primary_location_id) if training.primary_location_id else None
            from zoneinfo import ZoneInfo
            time_label=training.started_at.astimezone(ZoneInfo(training.timezone)).strftime(" %H:%M") if training.started_at else ""
            names = sector_names.get(training.id) or sorted({section.name for section in training.sections})
            sectors = ", ".join(names) if names else "Без сектора"
            label=f"{training.local_date:%d.%m.%Y}{time_label} · {region.name if region else 'Без района'} · {sectors}"+(" · текущая" if training.status=="active" else "")
            keyboard.append([button(label[:150],"tr:"+training.id)])
        if len(trainings)>10: keyboard.append([button("Далее",prefix+trainings[9].id)])
        keyboard.append([button("Скрыть тестовые тренировки" if include_test else "🧪 Показать также тестовые тренировки",
                                "trainings:0" if include_test else "trainings-test:0")])
        keyboard.append([button("← Журнал","journal")])
        await reply(session,job,("Выберите тренировку." if trainings else "Тренировок для выбранного фильтра нет.") +
                    ("\n🧪 Включены тестовые тренировки." if include_test else "\nТренировки только с тестовыми пролазами скрыты."),keyboard)
        return True
    if command.startswith("tr:"):
        training=await session.scalar(select(TrainingSession).where(TrainingSession.user_id==user.id,
            TrainingSession.id==command.removeprefix("tr:")))
        if not training: raise HTTPException(404,"Training not found")
        await dialog_set(session,user.id,"training_selected",{"form":"attempt_manage","training_id":training.id,
            "version":training.version,"ids":[]})
        await attempt_list(session,user.id,job,training,0,reply)
        return True
    if command.startswith("attempts:"):
        _, scope, offset = command.split(":")
        if not offset.isdigit():
            raise HTTPException(422, "Invalid list")
        training = await training_for(session, user.id, scope) if scope in ("current","last") else await session.scalar(
            select(TrainingSession).where(TrainingSession.user_id==user.id,TrainingSession.id==scope))
        if not training:
            await reply(session, job, "Тренировка не найдена.")
            return True
        await dialog_set(session,user.id,"training_selected",{"form":"attempt_manage","training_id":training.id,
            "version":training.version,"ids":[]})
        await attempt_list(session,user.id,job,training,int(offset),reply)
        return True
    if command.startswith("am:pick:"):
        item = await session.scalar(select(RouteAttempt).join(TrainingSession).where(
            RouteAttempt.id == command.removeprefix("am:pick:"), TrainingSession.user_id==user.id))
        if not item: raise HTTPException(404,"Attempt not found")
        if dialog and dialog.data.get("training_id") and dialog.data["training_id"]!=item.training_id:
            await reply(session,job,"Этот пролаз относится к другой тренировке. Сначала выберите её.",
                [[button("Выбрать тренировку этого пролаза","tr:"+item.training_id)]])
            return True
        training = await session.get(TrainingSession,item.training_id)
        editor_token = secrets.token_hex(8)
        await dialog_set(session,user.id,"attempt_edit",{"form":"attempt_manage","training_id":training.id,
            "version":training.version,"ids":[item.id],"editor_token":editor_token})
        keyboard = [[button(label,"am:field:"+editor_token+":"+field)] for field,label in (
            ("region","Район"),("sector","Сектор"),("name","Название"),("grade","Категория"),("clean_ascent","Чистота"),("reached_top","Дошёл до конца"),
            ("style","Стиль"),("belay","Страховка"),("falls","Срывы"),("hangs","Зависания"),("notes","Комментарий"),
            ("is_test","🧪 Тестовая запись"))]
        keyboard.append([button("💬 Изменить через LLM","am:ai:"+editor_token)])
        keyboard.append([button("🗑 Удалить попытку","am:askdelete")])
        keyboard.append([button("← Пролазы тренировки","tr:"+training.id)])
        keyboard.append([button("Закрыть","am:cancel")])
        await reply(session,job,await card(session,item),keyboard)
        return True
    if command == "am:select":
        if not dialog or not dialog.data.get("training_id"):
            await reply(session,job,"Сначала выберите тренировку.",[[button("Тренировки","trainings:0")]])
            return True
        training = await locked_training(session,user.id,dialog.data["training_id"],dialog.data["version"])
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
    if command != "/cancel" and (command.startswith(("stats:","training:","attempt:","profile","gear:","journal","test:")) or command.startswith("/")):
        return False
    if command in ("am:cancel","/cancel") or dialog.created_at < now()-timedelta(minutes=5):
        await session.delete(dialog)
        await reply(session,job,"Действие отменено.",menu(bool(await training_for(session,user.id,"current"))))
        return True
    data=dialog.data
    if command.startswith("am:ai:"):
        if command.removeprefix("am:ai:")!=data.get("editor_token"):
            await reply(session,job,"Карточка устарела. Выберите попытку заново.")
            return True
        dialog.state="training_selected"
        await reply(session,job,"Опишите изменения выбранного пролаза одним сообщением или голосом. Например: «Измени район на Крым, сектор на Красный камень».")
    elif dialog.state == "attempt_select_delete" and command.startswith(("am:toggle:","am:page:","am:all")):
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
    elif command.startswith("am:delete") and dialog.state=="attempt_delete":
        if command != "am:delete:"+data.get("confirmation", ""):
            await reply(session,job,"Подтверждение устарело. Используйте кнопку под актуальным списком попыток.")
            return True
        count,version=await delete_rows(session,user.id,data["training_id"],data["version"],data["ids"])
        await dialog_set(session,user.id,"training_selected",{"form":"attempt_manage","training_id":data["training_id"],"version":version,"ids":[]})
        await reply(session,job,f"Удалено попыток: {count}",[[button("← Пролазы тренировки","tr:"+data["training_id"])]])
    elif command.startswith("am:field:") and dialog.state=="attempt_edit":
        token, _, field = command.removeprefix("am:field:").partition(":")
        if token != data.get("editor_token"):
            await reply(session,job,"Карточка устарела. Выберите попытку заново.")
            return True
        if field not in AttemptChanges.model_fields: raise HTTPException(422,"Unknown field")
        value_token=secrets.token_hex(8)
        dialog.state,dialog.data="attempt_value",{**data,"field":field,"value_token":value_token}
        options=STYLE_NAMES if field=="style" else BELAY_NAMES if field=="belay" else {"yes":"Да","no":"Нет"} if field in ("clean_ascent","reached_top","is_test") else None
        await reply(session,job,"Выберите новое значение." if options else "Введите новое значение. /cancel — отмена.",
            [[button(label,"am:value:"+value_token+":"+value)] for value,label in options.items()] if options else None)
    elif dialog.state=="attempt_value":
        field=data["field"]
        value=command
        if command.startswith("am:value:"):
            token, _, value=command.removeprefix("am:value:").partition(":")
            if token != data.get("value_token"):
                await reply(session,job,"Кнопка устарела. Используйте актуальную карточку.")
                return True
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
        changed,version=await patch_rows(session,user.id,data["training_id"],data["version"],data["ids"],changes)
        await dialog_set(session,user.id,"training_selected",{"form":"attempt_manage","training_id":data["training_id"],"version":version,"ids":data["ids"]})
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
    training=await session.get(TrainingSession,data["training_id"])
    await reply(session,job,f"Выберите попытки тренировки {training.local_date:%d.%m.%Y} для удаления.",keyboard)


async def attempt_list(session, uid, job, training, start, reply):
    values=await rows(session,uid,training.id,limit=None)
    from app.tool_service import _summary, _duration_minutes
    region = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    sector_ids = {x.route_snapshot.get("sectorId") for x in values if x.route_snapshot.get("sectorId")}
    sectors = list((await session.scalars(select(Section.name).where(Section.id.in_(sector_ids)).order_by(Section.name))).all()) if sector_ids else []
    duration = _duration_minutes(training)
    overview = (f"🧗 Тренировка {training.local_date:%d.%m.%Y}\n"
                f"Статус: {'текущая' if training.status == 'active' else 'завершена'}\n"
                f"Регион: {region.name if region else 'Не указан'}\n"
                f"Секторы: {', '.join(sectors) if sectors else 'Не указаны'}\n"
                f"Продолжительность: {str(duration)+' мин' if duration is not None else 'Не указана'}\n\n"
                + summary(_summary(values)))
    test_count = sum(x.is_test for x in values)
    if test_count:
        overview += f"\n\n🧪 Тестовых записей: {test_count} — не включены в сводку."
    keyboard=[[button(("🧪 " if x.is_test else "")+f"№{x.sequence} · {(x.route_snapshot or {}).get('name')}"[:60],"am:pick:"+x.id)] for x in values[start:start+15]]
    if start+15<len(values): keyboard.append([button("Далее",f"attempts:{training.id}:{start+15}")])
    if start: keyboard.append([button("Назад",f"attempts:{training.id}:{max(0,start-15)}")])
    if training.status == "completed" and not await training_for(session, uid, "current"):
        latest = await training_for(session, uid, "last")
        if latest and latest.id == training.id:
            keyboard.append([button("↩️ Возобновить тренировку", "training:resume")])
    if training.status == "active":
        keyboard.extend(active_training_actions(training))
    else:
        keyboard.append([button("📅 Изменить дату",f"td:{training.id}:{training.version}")])
    keyboard.extend([[button("🗑 Выбрать несколько для удаления","am:select")],
                     [button("← Выбрать другую тренировку","trainings:0")]])
    await reply(session,job,overview+"\n\nВыберите пролаз для изменения или опишите изменения через LLM.",keyboard)

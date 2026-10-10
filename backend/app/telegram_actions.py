"""Deterministic UI and validated intent application; no response-formatting model."""
import hashlib
import hmac
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.access import decide_access, message, request_access, require_approver
from app.config import get_settings
from app.db import set_user_context
from app.models import ExternalRef, Gear, Location, TrainingSession, User
from app.public_models import AccessRequest, DeletionRecord, Job, Outbox, Usage, TelegramUpdate
from app.public_schemas import Intent
from app.telegram_format import attempts, button, menu, statistics, stats_menu
from app.tool_service import _active, _get_current, _get_trainings, _statistics, execute_tool, _gear_dict
from app.auth import user_payload
from app.jobs import now
from app.profile_service import ProfileService
from app.application_services import StatisticsService, TrainingService
from app.manual_form import handle as handle_manual_form


async def reply(session, job: Job, value: str, keyboard=None, suffix="", document=None, access_request_id=None):
    if len(value) <= 3500 or document:
        await message(session, job.user_id, job.payload["chat_id"], f"job:{job.id}{suffix}", value, keyboard, document, access_request_id)
    else:
        chunks, current = [], ""
        for line in value.splitlines():
            if len(current)+len(line)+1 > 3500:
                chunks.append(current)
                current = ""
            current += line[:3400]+"\n"
        chunks.append(current)
        for i, chunk in enumerate(chunks):
            await message(session, job.user_id, job.payload["chat_id"], f"job:{job.id}{suffix}:part:{i}", chunk,
                          keyboard if i == len(chunks)-1 else None)


async def complete(session, job: Job, intent: Intent | None = None, tokens: int = 0):
    user = await session.scalar(select(User).where(User.id == job.user_id).with_for_update())
    if not user:
        raise HTTPException(404, "Account deleted")
    await set_user_context(session, user.id)
    command = job.payload["command"]
    identity = {"user": {"id": user.id}}
    if command.startswith(("approve:", "reject:")):
        value = await decide_access(session, user, job.payload["telegram_id"], job.payload["chat_id"],
                                     command.split(":", 1)[1], command.startswith("approve:"), job.payload)
        await reply(session, job, value)
    elif command in ("/start", "/access", "access:request", "/status", "/help", "/privacy"):
        if command in ("/access", "access:request"):
            value = await request_access(session, user, job.payload["telegram_id"], job.payload.get("username"))
        elif command == "/privacy":
            value = "Журнал виден только вам. Текст и аудио для распознавания передаются в Cloud.ru. Экспорт и удаление доступны в профиле."
        else:
            status = {"active": "Доступ открыт", "pending_approval": "Ожидается подтверждение владельца", "blocked": "Доступ заблокирован"}[user.status]
            value = f"🧗 Climbing Journal\n{status}"
        keyboard = menu(bool(await _active(session, user.id))) if user.status == "active" else None if user.status == "blocked" else [[button("Запросить доступ", "access:request")]]
        await reply(session, job, value, keyboard)
    elif user.status != "active":
        await reply(session, job, "Нужен доступ владельца. Подайте заявку через /start.", [[button("Запросить доступ", "access:request")]])
    elif await handle_manual_form(session, user, job, reply):
        pass
    elif command in ("/journal", "journal"):
        await reply(session, job, "🧗 Журнал тренировок", menu(bool(await _active(session, user.id))))
    elif command in ("/stats", "stats:menu"):
        await reply(session, job, "📊 Статистика", stats_menu())
    elif command.startswith("stats:"):
        parts = command.split(":")
        scope = {"last-training": "last_training"}.get(parts[1], parts[1])
        if scope not in ("current", "last_training", "week", "month", "progress", "grades", "locations", "projects", "records"):
            raise HTTPException(422, "Unknown statistics scope")
        filters = {"scope": scope, **identity}
        if len(parts) == 3:
            filters["dateFrom"] = parts[2]
        dto = await TrainingService.current(session, identity) if scope == "current" else await StatisticsService.read(session, filters)
        keyboard = [[button("📋 Подробнее", "training:details:current" if scope == "current" else "training:details:last")],
                    [button("← Статистика", "stats:menu")]]
        await reply(session, job, statistics(dto), keyboard)
    elif command.startswith("training:details:"):
        if command.endswith("current"):
            dto = await TrainingService.current(session, {**identity, "detail": "full", "includeTest": user.test_mode_enabled})
        else:
            dto = (await StatisticsService.read(session, {**identity, "scope": "last_training", "detail": "full"})).get("training") or {}
        for i, chunk in enumerate(attempts(dto)):
            await reply(session, job, chunk, [[button("← Статистика", "stats:menu")]], f":{i}")
    elif command in ("training:start", "/training"):
        if await _active(session, user.id):
            await reply(session, job, "Тренировка уже начата.", menu(True))
        else:
            await execute_tool(session, "start_climbing_training", {**identity, "startedAt": now().isoformat()}, job.id)
            await reply(session, job, "Тренировка начата. Опишите трассу и попытку текстом или голосом.", menu(True))
    elif command in ("training:finish", "training:finish:cancel", "/finish"):
        pending = list((await session.scalars(select(Job).where(Job.user_id == user.id, Job.id != job.id,
                   Job.lane == "ai", Job.status.in_(["pending", "processing"])).with_for_update())).all())
        if pending and command != "training:finish:cancel":
            await reply(session, job, "Есть необработанные записи. Дождитесь ответов и завершите тренировку, либо отмените их.",
                        [[button("Отменить записи и завершить", "training:finish:cancel")], [button("Вернуться", "journal")]])
        else:
            for queued in pending:
                queued.status = "cancelled"
            if await _active(session, user.id):
                await execute_tool(session, "finish_climbing_training", identity, job.id)
            await reply(session, job, "Тренировка завершена.", menu(False))
    elif command in ("/profile", "profile"):
        await reply(session, job, f"👤 {user.name}\nЧасовой пояс: {user.timezone}\nТестовый режим: {'включён' if user.test_mode_enabled else 'выключен'}",
                    [[button("Имя", "profile:name"), button("Часовой пояс", "profile:timezone")], [button("Снаряжение", "gear:menu")],
                     [button("Экспорт", "profile:export")], [button("Удалить аккаунт", "profile:delete")], [button("← Главное меню", "journal")]])
    elif command in ("/gear", "gear:menu") or command.startswith("gear:menu:"):
        cursor = command.split(":", 2)[2] if command.startswith("gear:menu:") else ""
        query = select(Gear).where(Gear.user_id == user.id, Gear.id > cursor).order_by(Gear.id).limit(11)
        items = list((await session.scalars(query)).all())
        for item in items[:10]:
            await reply(session, job, f"{item.type}: {item.brand or ''} {item.model or ''}\nРазмер: {item.size or 'не указан'}\nАктивно: {'да' if item.active else 'нет'}",
                        [[button("Активировать/убрать", f"gear:toggle:{item.id}"), button("В текущую тренировку", f"gear:training:{item.id}")]], f":{item.id}")
        keyboard = [[button("Добавить", "gear:form")], [button("← Профиль", "profile")]]
        if len(items) > 10:
            keyboard.insert(0, [button("Следующая страница", f"gear:menu:{items[9].id}")])
        await reply(session, job, "Снаряжение" if items else "Снаряжения пока нет.", keyboard)
    elif command.startswith(("gear:toggle:", "gear:training:")):
        item_id = command.split(":", 2)[2]
        item = await session.scalar(select(Gear).where(Gear.id == item_id, Gear.user_id == user.id).with_for_update())
        if not item:
            raise HTTPException(404, "Gear not found")
        if command.startswith("gear:toggle:"):
            item.active = not item.active
            await reply(session, job, "Активность снаряжения обновлена.")
        else:
            active = await _active(session, user.id)
            if not active:
                await reply(session, job, "Сначала начните тренировку.", menu(False))
            else:
                if item in active.gear:
                    active.gear.remove(item)
                else:
                    active.gear.append(item)
                active.version += 1
                await reply(session, job, "Снаряжение тренировки обновлено.", menu(True))
    elif command == "profile:export":
        await reply(session, job, "Экспорт личных данных. Файл в очереди хранится до 24 часов.",
                    document=await ProfileService.export(session, user.id))
    elif command == "profile:delete":
        job.result = {"delete_confirmation": True}
        await reply(session, job, "Удалить журнал и аккаунт? Отменить удаление нельзя. Подтверждение действует 5 минут.",
                    [[button("Подтверждаю удаление", f"delete:{job.id}")], [button("Отмена", "profile")]])
    elif command.startswith("delete:"):
        confirmation = await session.scalar(select(Job).where(Job.id == command.split(":", 1)[1], Job.user_id == user.id).with_for_update())
        if not confirmation or confirmation.created_at < now()-timedelta(minutes=5) or not (confirmation.result or {}).get("delete_confirmation"):
            raise HTTPException(409, "Deletion confirmation expired")
        await ProfileService.delete(session, user.id, job.payload["telegram_id"])
        await message(session, None, job.payload["chat_id"], f"deleted:{job.id}", "Аккаунт и журнал удалены.")
        return
    elif command.startswith("test:"):
        if command == "test:menu":
            await reply(session, job, "Тестовые записи не участвуют в статистике.",
                        [[button("Включить", "test:on"), button("Выключить", "test:off")]])
        elif command in ("test:on", "test:off"):
            user.test_mode_enabled = command == "test:on"
            await reply(session, job, "Тестовый режим " + ("включён" if user.test_mode_enabled else "выключен"), menu(bool(await _active(session, user.id))))
    elif command.startswith("/requests"):
        await require_approver(session, user, job.payload["telegram_id"], job.payload["chat_id"])
        cursor = command.partition(" ")[2]
        query = select(AccessRequest).where(AccessRequest.status == "pending")
        if cursor:
            query = query.where(AccessRequest.id > cursor)
        items = list((await session.scalars(query.order_by(AccessRequest.id).limit(10))).all())
        for item in items:
            target = await session.get(User, item.user_id)
            await reply(session, job, f"{item.id}\n{target.name}", [[button("Разрешить", f"approve:{item.id}"), button("Отклонить", f"reject:{item.id}")]], f":{item.id}", access_request_id=item.id)
        await reply(session, job, f"Следующая страница: /requests {items[-1].id}" if len(items) == 10 else "Конец списка.")
    elif job.lane == "ai" and intent:
        if intent.kind == "statistics":
            filters = {**identity, "scope": intent.scope, "grade": intent.grade,
                       "dateFrom": intent.date_from.isoformat() if intent.date_from else None,
                       "dateTo": intent.date_to.isoformat() if intent.date_to else None}
            dto = await TrainingService.current(session, identity) if intent.scope == "current" else await StatisticsService.read(session, filters)
            await reply(session, job, statistics(dto), [[button("← Статистика", "stats:menu")]])
        elif intent.kind == "attempt":
            training = await _active(session, user.id)
            if not training or training.id != job.training_id:
                await reply(session, job, "Запись не сохранена: тренировка завершена или не была начата. Начните тренировку и повторите запись.", menu(bool(training)))
            elif not intent.continue_current_route and (not intent.name or not intent.grade):
                await reply(session, job, "Уточните название и категорию трассы; запись пока не сохранена.")
            else:
                raw = {"name": intent.name, "grade": intent.grade, "attempts": intent.attempts,
                       "reachedTop": intent.reached_top, "cleanAscent": intent.clean_ascent,
                       "falls": intent.falls, "hangs": intent.hangs, "style": intent.style, "belay": intent.belay,
                       "notes": intent.notes, "isTest": user.test_mode_enabled or intent.is_test or command.casefold().startswith("тест")}
                raw = {k: v for k, v in raw.items() if v is not None}
                if intent.continue_current_route:
                    raw.pop("name", None)
                    raw.pop("grade", None)
                    raw["continueCurrentRoute"] = True
                if intent.hangs:
                    raw["cleanAscent"] = False
                    raw["notes"] = (raw["notes"] or "") + f"; зависания: {intent.hangs}"
                dto = await execute_tool(session, "append_climbing_attempt", {**identity, "date": training.local_date.isoformat(), "attempt": raw}, job.id)
                await reply(session, job, f"Сохранено: {intent.name} {intent.grade}\nЧисто: {dto['outcome']['cleanAscent']}\nСтиль: {intent.style}\nСтраховка: {intent.belay}", menu(True))
        else:
            await reply(session, job, intent.question or "Уточните трассу, категорию и результат попытки.")
        if job.reservation_day:
            usage = await session.scalar(select(Usage).where(Usage.scope == user.id, Usage.day == job.reservation_day).with_for_update())
            if usage:
                usage.tokens += tokens
    else:
        await reply(session, job, "Очередь AI заполнена. Дождитесь ответа или запишите попытку через форму." if command == "quota:queued" else "Используйте /journal или опишите попытку текстом/голосом.")
    job.status, job.lease_until, job.worker_id = "succeeded", None, None

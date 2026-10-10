import hashlib
import hmac

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import set_user_context
from app.models import ExternalRef, Gear, Location, Route, Section, TrainingSession, User
from app.public_models import DeletionRecord, TelegramUpdate, Usage
from app.tool_service import _get_trainings, _gear_dict


class ProfileService:
    @staticmethod
    async def export(session, uid: str):
        await set_user_context(session, uid)
        user = await session.get(User, uid)
        history = await _get_trainings(session, {"user": {"id": uid}, "includeTest": True}, export_all=True)
        gear = list((await session.scalars(select(Gear).where(Gear.user_id == uid))).all())
        locations = list((await session.scalars(select(Location).where(Location.owner_id == uid))).all())
        sections = list((await session.scalars(select(Section).where(Section.location_id.in_([x.id for x in locations])))).all())
        routes = list((await session.scalars(select(Route).where(Route.section_id.in_([x.id for x in sections])))).all())
        updates = list((await session.scalars(select(TelegramUpdate).where(TelegramUpdate.user_id == uid))).all())
        return {"profile": {"id": uid, "name": user.name, "timezone": user.timezone, "testMode": user.test_mode_enabled},
                "trainings": history["trainings"], "gear": [_gear_dict(x) for x in gear],
                "catalog": {"locations": [{"id": x.id, "name": x.name, "country": x.country} for x in locations],
                            "sections": [{"id": x.id, "locationId": x.location_id, "name": x.name} for x in sections],
                            "routes": [{"id": x.id, "sectionId": x.section_id, "name": x.name, "grade": x.grade} for x in routes]},
                "telegramUpdates": [x.payload for x in updates]}

    @staticmethod
    async def delete(session, uid: str, telegram_id: str):
        await session.scalar(select(User).where(User.id == uid).with_for_update())
        await set_user_context(session, uid)
        digest = hmac.new(get_settings().internal_api_key.get_secret_value().encode(), telegram_id.encode(), hashlib.sha256).hexdigest()
        session.add(DeletionRecord(identity_hash=digest, user_id=uid))
        await session.execute(delete(TrainingSession).where(TrainingSession.user_id == uid))
        await session.execute(delete(Gear).where(Gear.user_id == uid))
        await session.execute(delete(Location).where(Location.owner_id == uid))
        await session.execute(delete(Usage).where(Usage.scope == uid))
        await session.execute(delete(User).where(User.id == uid))

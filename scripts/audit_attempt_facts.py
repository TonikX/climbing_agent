"""Read-only verified-owner export for reviewing facts before migration 20261022_0020.

Run inside an API container with the existing DB credentials; journal reads use owner context and RLS.
"""
import argparse
import asyncio
import csv
from pathlib import Path
from sqlalchemy import select
from app.db import ControlSessionFactory, SessionFactory, set_user_context, engine, control_engine
from app.config import get_settings
from app.models import ExternalRef, RouteAttempt, TrainingSession


async def audit(destination):
    records = []
    async with ControlSessionFactory() as control:
        uid = await control.scalar(select(ExternalRef.user_id).where(ExternalRef.system == 'telegram',
            ExternalRef.entity_type == 'user', ExternalRef.external_id == get_settings().access_approver_telegram_id))
    if not uid:
        raise RuntimeError('Verified owner account not found')
    async with SessionFactory() as session:
        await set_user_context(session, uid)
        rows = await session.execute(select(RouteAttempt, TrainingSession.local_date).join(TrainingSession)
            .where(TrainingSession.user_id == uid).order_by(TrainingSession.local_date, RouteAttempt.sequence))
        for item, day in rows:
            style, belay, top, clean = item.style, item.belay, item.reached_top, item.clean_ascent
            conflict = style == "top_rope" and belay not in (None, "unknown", "top_rope")
            if style == "top_rope" and not conflict:
                belay = "top_rope"
                style = "with_falls" if item.falls else "with_hangs" if item.hangs else "unknown"
            if top is False or item.falls or item.hangs or style in ("with_falls", "with_hangs"):
                clean = False
            if top is None and (clean is True or item.result == "send"):
                top = True
            missing = [key for key, value in (("reached_top", top), ("clean_ascent", clean)) if value is None]
            if belay in (None, "unknown"):
                missing.append("belay")
            if conflict:
                missing.append("style/belay conflict")
            if missing or item.style == "top_rope":
                records.append(dict(id=item.id, training_id=item.training_id, date=day,
                    name=(item.route_snapshot or {}).get("name"), is_test=item.is_test,
                    style=item.style, belay=item.belay, reached_top=item.reached_top, clean_ascent=item.clean_ascent,
                    falls=item.falls, hangs=item.hangs, notes=item.notes,
                    proposed_style=style, proposed_belay=belay, missing_fields=", ".join(missing)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ("id", "training_id", "date", "name", "is_test", "style", "belay", "reached_top", "clean_ascent",
                  "falls", "hangs", "notes", "proposed_style", "proposed_belay", "missing_fields")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    print(f"Review needed: {sum(bool(row['missing_fields']) for row in records)}; upper-style records: {sum(row['style']=='top_rope' for row in records)}")
    await control_engine.dispose()
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/attempt-facts-review.csv"))
    asyncio.run(audit(parser.parse_args().output))

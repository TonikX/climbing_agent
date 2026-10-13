"""Idempotent public catalogue import, with an advisory lock and durable report."""
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalRef, Location, Section, Route
from app.import_models import CatalogImportRun
from app.allclimb_html import COUNTRIES

LOCK = 718394139489


async def upsert(session, records):
    counts = {key: 0 for key in ("created", "updated", "unchanged")}
    objects = {}
    for record in sorted(records.values(), key=lambda r: ({"location": 0, "section": 1, "route": 2}[r.kind], r.url)):
        ref = await session.scalar(select(ExternalRef).where(ExternalRef.system == "allclimb",
            ExternalRef.entity_type == record.kind, ExternalRef.external_id == record.external_id))
        model = {"location": Location, "section": Section, "route": Route}[record.kind]
        item = await session.get(model, getattr(ref, record.kind + "_id")) if ref else None
        parent = objects.get(record.parent)
        if record.kind != "location" and parent is None:
            raise ValueError("Missing or unverified parent catalogue entry")
        values = {"name": record.name}
        if record.kind == "location":
            if item and (item.visibility != "public" or item.owner_id is not None or item.country != COUNTRIES[record.country]):
                raise ValueError("Refusing to overwrite a private or conflicting catalogue location")
            values.update(country=COUNTRIES[record.country], visibility="public", owner_id=None, type="outdoor")
            if record.region:
                values["region"] = record.region
        elif record.kind == "section":
            if item and item.location_id != parent.id:
                raise ValueError("Source sector changed parent; manual review required")
            values.update(location_id=parent.id, type="sector")
        else:
            if item and item.section_id != parent.id:
                raise ValueError("Source route changed parent; manual review required")
            values["section_id"] = parent.id
            if record.grade is not None:
                values["grade"] = record.grade
        if not item:
            item = model(**values)
            session.add(item)
            await session.flush()
            session.add(ExternalRef(system="allclimb", entity_type=record.kind, external_id=record.external_id,
                url=record.url, **{record.kind + "_id": item.id}))
            counts["created"] += 1
        else:
            changed = any(getattr(item, key) != value for key, value in values.items()) or ref.url != record.url
            for key, value in values.items():
                setattr(item, key, value)
            ref.url = record.url
            counts["updated" if changed else "unchanged"] += 1
        objects[record.url] = item
    await session.flush()
    return counts


async def import_catalog(engine, collect):
    async with engine.connect() as connection:
        if not await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            await connection.rollback()
            raise RuntimeError("Another catalogue import is running")
        await connection.commit()
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await session.execute(update(CatalogImportRun).where(CatalogImportRun.source == "allclimb",
                    CatalogImportRun.status == "running").values(status="interrupted", finished_at=datetime.now(UTC),
                    error="Previous process ended without completing its report"))
                run = CatalogImportRun(status="running", report={"coverage": "partial_html"})
                session.add(run)
                await session.commit()
                run_id = run.id
                try:
                    records, report = await collect()
                    report.update(await upsert(session, records))
                    # HTML discovery cannot certify a country's entire catalogue.
                    run.status, run.report, run.finished_at = "partial", report, datetime.now(UTC)
                    await session.commit()
                    return {"run_id": run_id, "status": run.status, **report}
                except Exception as exc:
                    await session.rollback()
                    run = await session.get(CatalogImportRun, run_id)
                    run.status, run.error, run.finished_at = "failed", type(exc).__name__ + ": " + str(exc)[:500], datetime.now(UTC)
                    await session.commit()
                    raise
        finally:
            await connection.rollback()
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
            await connection.commit()

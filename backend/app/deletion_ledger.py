"""Operator-only ledger export/replay; the file is independent of journal backups."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.db import ControlSessionFactory, set_user_context
from app.models import Gear, Location, TrainingSession, User
from app.public_models import DeletionRecord, Usage


async def run(args):
    async with ControlSessionFactory() as session, session.begin():
        if args.export:
            rows = list((await session.scalars(select(DeletionRecord).order_by(DeletionRecord.created_at))).all())
            print(json.dumps([{"user_id": x.user_id, "identity_hash": x.identity_hash,
                               "created_at": x.created_at.isoformat()} for x in rows]))
        else:
            # Run before starting API/workers, using the privileged migration connection.
            records = json.loads(Path(args.replay).read_text(encoding="utf-8"))
            if not isinstance(records, list) or any(not isinstance(x.get("user_id"), str) for x in records):
                raise ValueError("Invalid ledger")
            for record in records:
                uid = record["user_id"]
                await set_user_context(session, uid)
                await session.execute(delete(TrainingSession).where(TrainingSession.user_id == uid))
                await session.execute(delete(Gear).where(Gear.user_id == uid))
                await session.execute(delete(Location).where(Location.owner_id == uid))
                await session.execute(delete(Usage).where(Usage.scope == uid))
                await session.execute(delete(User).where(User.id == uid))
                # Preserve post-backup deletions in subsequent ledger exports too.
                if not await session.scalar(select(DeletionRecord.id).where(DeletionRecord.user_id == uid).limit(1)):
                    session.add(DeletionRecord(user_id=uid, identity_hash=record["identity_hash"],
                                               created_at=datetime.fromisoformat(record["created_at"])))
            print("Applied deletion ledger")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true")
    group.add_argument("--replay")
    asyncio.run(run(parser.parse_args()))

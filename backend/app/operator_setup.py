"""Explicit server-side setup of the human-verified approver, never first-user admin."""
import asyncio

from app.access import telegram_user
from app.config import get_settings
from app.db import ControlSessionFactory
from app.public_models import AuditEvent


async def main():
    cfg = get_settings()
    tid = cfg.access_approver_telegram_id
    if not tid or not tid.isdigit() or int(tid) <= 0 or cfg.access_approval_chat_id != tid:
        raise ValueError("Configure the verified Telegram user ID and matching private chat ID first")
    async with ControlSessionFactory() as session, session.begin():
        user = await telegram_user(session, tid)
        if user.status == "blocked":
            raise ValueError("Blocked approver requires an explicit operator review")
        user.status, user.role = "active", "admin"
        session.add(AuditEvent(actor_id="server-operator", action="approver:setup", subject_id=user.id))
    print("Configured approver activated. No other account changed.")


if __name__ == "__main__":
    asyncio.run(main())

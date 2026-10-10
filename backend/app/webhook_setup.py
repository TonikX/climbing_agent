"""Explicit operator command; never changes polling/webhook during API startup."""
import asyncio
import os
from urllib.parse import urlparse

from aiogram import Bot

from app.config import get_settings


async def main():
    cfg = get_settings()
    url = os.environ["TELEGRAM_WEBHOOK_URL"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.path != "/telegram/webhook" or not parsed.hostname:
        raise ValueError("Use https://your-domain/telegram/webhook")
    secret = cfg.telegram_webhook_secret.get_secret_value()
    if len(secret) < 32:
        raise ValueError("Use a random webhook secret of at least 32 characters")
    async with Bot(cfg.telegram_bot_token.get_secret_value()) as bot:
        identity = await bot.get_me()
        if str(identity.id) != cfg.telegram_bot_id:
            raise ValueError("TELEGRAM_BOT_ID does not match this bot token")
        await bot.set_webhook(url, secret_token=secret, drop_pending_updates=False,
                              allowed_updates=["message", "callback_query"], max_connections=40)
        print("Webhook configured; pending updates preserved")


if __name__ == "__main__":
    asyncio.run(main())

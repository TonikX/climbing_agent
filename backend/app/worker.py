"""Workers have no database credentials and act only on API-issued leases."""
import asyncio
import contextlib
import json
import logging
import sys
from uuid import uuid4

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from app.ai_provider import interpret
from app.config import get_settings

log = logging.getLogger("worker")


async def run(lane: str):
    if lane not in ("fast", "ai", "delivery"):
        raise ValueError("Unknown worker lane")
    cfg, worker_id = get_settings(), str(uuid4())
    bot = Bot(cfg.telegram_bot_token.get_secret_value()) if lane in ("ai", "delivery") else None
    async with httpx.AsyncClient(base_url=cfg.api_url, headers={"X-API-Key": cfg.internal_api_key.get_secret_value()}, timeout=30) as client:
        async def post(path, payload):
            response = await client.post("/api/v1/internal/" + path, json=payload)
            response.raise_for_status()
            return response.json()

        async def heartbeat(item_id):
            while True:
                await asyncio.sleep(30)
                await post(f"jobs/{lane}/{item_id}/heartbeat", {"worker_id": worker_id})

        try:
            maintenance_at = 0
            while True:
                try:
                    if lane == "fast" and asyncio.get_running_loop().time() >= maintenance_at:
                        await post("maintenance/retention", {})
                        maintenance_at = asyncio.get_running_loop().time() + 60
                    item = (await post("jobs/claim", {"lane": lane, "worker_id": worker_id}))["item"]
                except httpx.HTTPError:
                    await asyncio.sleep(2)
                    continue
                if not item:
                    await asyncio.sleep(0.5)
                    continue
                pulse = asyncio.create_task(heartbeat(item["id"]))
                result = {"worker_id": worker_id}
                retry, code = 0, "processing_failed"
                try:
                    if lane == "ai":
                        async def guard():
                            await post(f"jobs/{lane}/{item['id']}/heartbeat", {"worker_id": worker_id})
                        work = asyncio.create_task(interpret(item["payload"], bot, guard))
                        try:
                            done, _ = await asyncio.wait([work, pulse], return_when=asyncio.FIRST_COMPLETED)
                            if pulse in done:
                                pulse.result()
                            intent, tokens = await work
                        finally:
                            if not work.done():
                                work.cancel()
                                with contextlib.suppress(asyncio.CancelledError, Exception):
                                    await work
                        result.update(intent=intent.model_dump(mode="json"), tokens=tokens)
                    elif lane == "delivery":
                        payload = item["payload"]
                        markup = InlineKeyboardMarkup.model_validate(payload["reply_markup"]) if payload.get("reply_markup") else None
                        if "callback_id" in payload:
                            await bot.answer_callback_query(payload["callback_id"])
                        elif "document" in payload:
                            document = BufferedInputFile(json.dumps(payload["document"], ensure_ascii=False).encode(), "climbing-journal.json")
                            sent = await bot.send_document(item["chat_id"], document, caption=payload["text"][:1000])
                            result["telegram_message_id"] = sent.message_id
                        else:
                            sent = await bot.send_message(item["chat_id"], payload["text"], reply_markup=markup)
                            result["telegram_message_id"] = sent.message_id
                    if pulse.done():
                        pulse.result()  # Do not apply a result after heartbeat failure.
                    await post(f"jobs/{lane}/{item['id']}/complete", result)
                    log.info("completed lane=%s item=%s", lane, item["id"])
                except TelegramRetryAfter as exc:
                    retry, code = min(int(exc.retry_after)+1, 3600), "telegram_rate_limit"
                except TelegramForbiddenError:
                    code = "telegram_forbidden"
                except httpx.HTTPStatusError as exc:
                    code = "upstream_http"
                    if exc.response.status_code == 429 or exc.response.status_code >= 500:
                        try:
                            retry = min(max(int(exc.response.headers.get("Retry-After", "10")), 1), 3600)
                        except ValueError:
                            retry = 10
                except (httpx.TransportError, TimeoutError):
                    retry, code = 10, "network_timeout"
                except Exception:
                    code = "invalid_result"
                else:
                    code = ""
                finally:
                    pulse.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await pulse
                if code:
                    # Log only identifiers/codes: exception strings can contain bot tokens/audio URLs.
                    log.warning("failed lane=%s item=%s code=%s", lane, item["id"], code)
                    with contextlib.suppress(httpx.HTTPError):
                        await post(f"jobs/{lane}/{item['id']}/fail", {"worker_id": worker_id, "code": code, "retry_seconds": retry})
        finally:
            if bot:
                await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(sys.argv[1]))

"""Telegram webhook receiver: acknowledge only after the API commits durable ingress."""
import secrets
from contextlib import asynccontextmanager

import httpx
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from app.config import get_settings


@asynccontextmanager
async def lifespan(app):
    cfg = get_settings()
    if not cfg.telegram_webhook_secret.get_secret_value():
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required")
    app.state.client = httpx.AsyncClient(base_url=cfg.api_url, headers={"X-API-Key": cfg.internal_api_key.get_secret_value()}, timeout=15)
    yield
    await app.state.client.aclose()


app = FastAPI(title="Climbing Telegram ingress", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def webhook(request: Request):
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = get_settings().telegram_webhook_secret.get_secret_value()
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "Invalid webhook secret")
    # Check authentication before reading the body, then cap streaming bytes too.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 128_000:
            raise HTTPException(413, "Update too large")
    try:
        update = Update.model_validate_json(body)
    except (ValidationError, ValueError):
        raise HTTPException(422, "Invalid update")
    try:
        result = await request.app.state.client.post("/api/v1/internal/telegram/updates", json=update.model_dump(mode="json", exclude_none=True))
        result.raise_for_status()
    except httpx.HTTPError:
        # Telegram retries: never return 200 on a failed or uncertain commit.
        raise HTTPException(503, "Ingress temporarily unavailable")
    return {"ok": True}

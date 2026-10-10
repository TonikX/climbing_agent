"""Provider boundaries without real paid requests."""
import io
import json
import shutil
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import SecretStr

from app.ai_provider import interpret
from app.config import get_settings


class ProviderContractTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, voice=False):
        calls = []
        def provider(request):
            calls.append(request.url.path)
            if request.url.path.endswith("audio/transcriptions"):
                return httpx.Response(200, json={"text": "Трасса 6B flash"})
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "kind": "attempt", "name": "Трасса", "grade": "6B", "style": "flash"})}}], "usage": {"total_tokens": 42}})
        original = httpx.AsyncClient
        cfg = get_settings().model_copy(update={"cloudru_api_key": SecretStr("fake")})
        fake_bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path="voice", file_size=1000)))
        sample = io.BytesIO()
        with wave.open(sample, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        async def download(path, destination, timeout):
            destination.write(sample.getvalue())
        fake_bot.download_file = download
        payload = {"command": "Трасса 6B flash", "local_date": "2026-10-10"}
        if voice:
            payload.update(command="", voice={"file_id": "test"})
        guard = AsyncMock()
        with patch("app.ai_provider.get_settings", return_value=cfg), patch("app.ai_provider.httpx.AsyncClient",
                side_effect=lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(provider))):
            result, tokens = await interpret(payload, fake_bot, guard)
        self.assertEqual(result.name, "Трасса")
        self.assertEqual(tokens, 42)
        self.assertEqual(calls.count("/v1/chat/completions"), 1)
        self.assertEqual(calls.count("/v1/audio/transcriptions"), int(voice))
        self.assertEqual(guard.await_count, 2 if voice else 1)

    async def test_free_text_calls_one_intent_model_only(self):
        await self.exercise()

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is provided by the production Docker image")
    async def test_voice_calls_asr_then_one_intent_model(self):
        await self.exercise(voice=True)

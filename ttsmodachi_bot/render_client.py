from __future__ import annotations

import aiohttp

from .voices import VoiceParams


class RendererClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def render(self, text: str, voice: VoiceParams) -> bytes:
        session = self.session
        if session is None:
            session = aiohttp.ClientSession()
            self.session = session
        async with session.post(
            f"{self.base_url}/render",
            json={"text": text, "voice": voice.to_dict(), "mode": "text"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status >= 400:
                detail = await response.text()
                raise RuntimeError(f"Renderer failed with HTTP {response.status}: {detail}")
            return await response.read()


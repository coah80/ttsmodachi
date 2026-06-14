from __future__ import annotations

import asyncio

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
        last_error: BaseException | None = None
        for attempt in range(4):
            session = self.session
            if session is None or session.closed:
                session = aiohttp.ClientSession()
                self.session = session
            try:
                async with session.post(
                    f"{self.base_url}/render",
                    json={"text": text, "voice": voice.to_dict(), "mode": "text"},
                    timeout=aiohttp.ClientTimeout(total=35),
                ) as response:
                    if response.status >= 500 and attempt < 3:
                        last_error = RuntimeError(f"Renderer failed with HTTP {response.status}: {await response.text()}")
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    if response.status >= 400:
                        detail = await response.text()
                        raise RuntimeError(f"Renderer failed with HTTP {response.status}: {detail}")
                    return await response.read()
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as error:
                last_error = error
                if attempt >= 3:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error


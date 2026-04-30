from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .audio import amplify_wav
from .env import env_int, env_value
from .engines import ENGINES
from .panel import PANEL_HTML
from .panel_tokens import PanelSession, parse_panel_token
from .renderer_pool import RenderPayload, RendererPool
from .storage import Storage
from .voices import BUILTIN_VOICES, LANG_TO_ID, VoiceParams, cache_key


class RenderRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: dict[str, int | str] = Field(default_factory=dict)
    mode: Literal["text", "sing"] = "text"


class SaveVoiceRequest(BaseModel):
    voice: dict[str, int | str] = Field(default_factory=dict)


app = FastAPI(title="TTSModachi Renderer", version="0.1.0")
pool: RendererPool | None = None
storage: Storage | None = None
cache_dir = Path(env_value("TTSMODACHI_CACHE_DIR", "/cache") or "/cache")
database_path = Path(os.environ.get("DATABASE_PATH", "/data/ttsmodachi.sqlite3"))
engine_version = env_value("TTSMODACHI_ENGINE_VERSION", "ttsmodachi-v1") or "ttsmodachi-v1"
inflight_lock = asyncio.Lock()
inflight_tasks: dict[str, asyncio.Task[dict[str, object]]] = {}
render_semaphore: asyncio.Semaphore | None = None
max_inflight_renders = env_int("TTSMODACHI_MAX_INFLIGHT_RENDERS", 32)
cache_max_bytes = env_int("TTSMODACHI_CACHE_MAX_BYTES", 1024 * 1024 * 1024)
panel_token = env_value("TTSMODACHI_PANEL_TOKEN")
public_hosts = {
    host.strip().lower()
    for host in (env_value("TTSMODACHI_PUBLIC_HOSTS", "") or "").split(",")
    if host.strip()
}


@app.on_event("startup")
async def startup() -> None:
    global pool, render_semaphore, storage
    cache_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(database_path)
    pool = RendererPool.from_env()
    render_semaphore = asyncio.Semaphore(max_inflight_renders)
    pool.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    if pool is not None:
        pool.stop()
    if storage is not None:
        storage.close()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "cache_dir": str(cache_dir), "pool": pool.health() if pool else None}


@app.get("/", response_class=HTMLResponse)
async def panel() -> HTMLResponse:
    return HTMLResponse(PANEL_HTML)


@app.get("/api/config")
async def config(request: Request) -> dict[str, object]:
    require_panel_token(request)
    return {
        "builtins": {name: voice.to_dict() for name, voice in BUILTIN_VOICES.items()},
        "engines": {engine_id: info.__dict__ for engine_id, info in ENGINES.items()},
        "languages": sorted(LANG_TO_ID),
        "defaultMessage": "This is a test message for the discord bot.",
        "maxSafeSamples": 48,
    }


@app.get("/api/session")
async def session(request: Request) -> dict[str, object]:
    panel_session = require_panel_session(request)
    store = storage_for()
    voice_id = store.get_global_user_default(panel_session.user_id) or store.get_user_default(
        panel_session.guild_id,
        panel_session.user_id,
    )
    settings = store.get_guild_settings(panel_session.guild_id)
    effective_voice_id = voice_id or settings.default_voice_id
    voice = store.resolve_voice(effective_voice_id, panel_session.guild_id, panel_session.user_id)
    return {
        "guildId": panel_session.guild_id,
        "userId": panel_session.user_id,
        "displayName": panel_session.display_name,
        "avatarUrl": panel_session.avatar_url,
        "voiceId": effective_voice_id,
        "voice": voice.to_dict(),
        "expiresAt": panel_session.expires_at,
    }


@app.post("/api/voice/save")
async def save_voice(request: Request, payload: SaveVoiceRequest) -> dict[str, object]:
    panel_session = require_panel_session(request)
    try:
        voice = VoiceParams.from_mapping(payload.voice)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    store = storage_for()
    voice_id = "panel"
    store.save_global_user_voice(
        user_id=panel_session.user_id,
        voice_id=voice_id,
        name="Panel voice",
        voice=voice,
    )
    return {
        "ok": True,
        "voiceId": voice_id,
        "voice": voice.to_dict(),
    }


@app.post("/render")
async def render(request: Request, payload: RenderRequest) -> Response:
    require_panel_token(request)
    if pool is None:
        raise HTTPException(status_code=503, detail="Renderer pool is not ready")
    try:
        voice = VoiceParams.from_mapping(payload.voice)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    text = payload.text.replace("\n", " ").strip()
    if len(text) > voice.text_limit():
        raise HTTPException(status_code=400, detail=f"Text is longer than {voice.text_limit()} characters")

    key = cache_key(text, voice, payload.mode, engine_version)
    cache_path = cache_dir / f"{key}.wav"
    if cache_path.exists():
        return FileResponse(cache_path, media_type="audio/wav", filename="speech.wav", headers={"X-Cache": "HIT"})

    created = False
    async with inflight_lock:
        task = inflight_tasks.get(key)
        if task is None:
            if len(inflight_tasks) >= max_inflight_renders:
                raise HTTPException(status_code=429, detail="Renderer queue is full")
            task = asyncio.create_task(_render_to_cache(cache_path, text, voice, payload.mode))
            inflight_tasks[key] = task
            created = True

    try:
        result = await task
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    finally:
        if created:
            async with inflight_lock:
                if inflight_tasks.get(key) is task:
                    del inflight_tasks[key]

    cache_header = str(result["cache"])
    if cache_header == "MISS" and not created:
        cache_header = "DEDUPED"
    return FileResponse(
        cache_path,
        media_type="audio/wav",
        filename="speech.wav",
        headers={"X-Cache": cache_header, "X-Render-Time-Ms": str(result.get("elapsed_ms", ""))},
    )


async def _render_to_cache(cache_path: Path, text: str, voice: VoiceParams, mode: str) -> dict[str, object]:
    if cache_path.exists():
        return {"cache": "HIT", "elapsed_ms": ""}
    if pool is None or render_semaphore is None:
        raise RuntimeError("Renderer pool is not ready")

    async with render_semaphore:
        if cache_path.exists():
            return {"cache": "HIT", "elapsed_ms": ""}
        result = await asyncio.to_thread(pool.render, RenderPayload(text=text, voice=voice, mode=mode))
        audio = amplify_wav(result["audio"], voice.volume)
        with NamedTemporaryFile(dir=cache_dir, delete=False) as temp:
            temp.write(audio)
            temp_path = Path(temp.name)
        temp_path.replace(cache_path)
        prune_cache()
        return {"cache": "MISS", "elapsed_ms": result.get("elapsed_ms", "")}


def prune_cache() -> None:
    if cache_max_bytes <= 0:
        return

    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in cache_dir.glob("*.wav"):
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        entries.append((stat.st_mtime, stat.st_size, path))

    if total <= cache_max_bytes:
        return

    for _, size, path in sorted(entries):
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        if total <= cache_max_bytes:
            return


def require_panel_token(request: Request) -> None:
    if not panel_token or not is_public_request(request):
        return
    request_token = request.headers.get("x-panel-token") or request.query_params.get("token") or ""
    if hmac.compare_digest(request_token, panel_token):
        return
    try:
        parse_panel_token(request_token)
        return
    except ValueError:
        raise HTTPException(status_code=401, detail="Panel token required")


def require_panel_session(request: Request) -> PanelSession:
    token = request.headers.get("x-panel-token") or request.query_params.get("token") or ""
    try:
        return parse_panel_token(token)
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


def storage_for() -> Storage:
    if storage is None:
        raise HTTPException(status_code=503, detail="Storage is not ready")
    return storage


def is_public_request(request: Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    return bool(host and host in public_hosts)


def main() -> None:
    import uvicorn

    host = os.environ.get("RENDERER_HOST", "0.0.0.0")
    port = int(os.environ.get("RENDERER_PORT", "8080"))
    uvicorn.run("ttsmodachi_bot.renderer_service:app", host=host, port=port)


if __name__ == "__main__":
    main()

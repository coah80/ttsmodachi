from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import os
import time
import urllib.parse
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio import amplify_wav
from .env import env_int, env_value
from .engines import ENGINES
from .panel import LANDING_HTML, PANEL_HTML, PRIVACY_POLICY_HTML, TOS_HTML
from .panel_tokens import PanelSession, parse_panel_token
from .prosody import add_grammar_pauses
from .renderer_pool import RenderPayload, RendererPool
from .storage import Storage
from .voices import BUILTIN_VOICES, LANG_TO_ID, LANG_TO_ROM, VoiceParams, cache_key


LOGGER = logging.getLogger(__name__)


class RenderRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: dict[str, int | str] = Field(default_factory=dict)
    mode: Literal["text", "sing"] = "text"


class SaveVoiceRequest(BaseModel):
    voice: dict[str, int | str] = Field(default_factory=dict)


mimetypes.add_type("image/webp", ".webp")
app = FastAPI(title="TTSModachi Renderer", version="0.1.0")
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
pool: RendererPool | None = None
storage: Storage | None = None
cache_dir = Path(env_value("TTSMODACHI_CACHE_DIR", "/cache") or "/cache")
database_path = Path(os.environ.get("DATABASE_PATH", "/data/ttsmodachi.sqlite3"))
engine_version = env_value("TTSMODACHI_ENGINE_VERSION", "ttsmodachi-v1") or "ttsmodachi-v1"
output_gain_percent = max(25, min(300, env_int("TTSMODACHI_OUTPUT_GAIN_PERCENT", 125)))
grammar_pauses = (env_value("TTSMODACHI_GRAMMAR_PAUSES", "true") or "true").lower() not in {"0", "false", "no", "off"}
inflight_lock = asyncio.Lock()
inflight_tasks: dict[str, asyncio.Task[dict[str, object]]] = {}
render_semaphore: asyncio.Semaphore | None = None
max_inflight_renders = env_int("TTSMODACHI_MAX_INFLIGHT_RENDERS", 32)
cache_max_bytes = env_int("TTSMODACHI_CACHE_MAX_BYTES", 1024 * 1024 * 1024)
cache_prune_interval_seconds = env_int("TTSMODACHI_CACHE_PRUNE_INTERVAL_SECONDS", 300)
cache_prune_next_at = 0.0
cache_prune_task: asyncio.Task[None] | None = None
panel_token = env_value("TTSMODACHI_PANEL_TOKEN")
main_bot_client_id = env_value("TTSMODACHI_BOT_CLIENT_ID")
main_bot_invite_permissions = env_int("TTSMODACHI_INVITE_PERMISSIONS", 36785216)
second_bot_client_id = env_value("TTSMODACHI_SECOND_BOT_CLIENT_ID")
second_bot_invite_permissions = env_int("TTSMODACHI_SECOND_BOT_INVITE_PERMISSIONS", 36785216)
second_bot_invite_url = env_value("TTSMODACHI_SECOND_BOT_INVITE_URL")
support_invite_url = env_value("TTSMODACHI_SUPPORT_INVITE_URL")
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
async def panel(request: Request) -> HTMLResponse:
    if request.query_params.get("token"):
        return HTMLResponse(PANEL_HTML)
    return HTMLResponse(LANDING_HTML)



@app.head("/tos")
async def terms_of_service_head() -> Response:
    return Response(status_code=200, media_type="text/html")


@app.get("/tos", response_class=HTMLResponse)
async def terms_of_service() -> HTMLResponse:
    return HTMLResponse(TOS_HTML)


@app.head("/privacy-policy")
async def privacy_policy_head() -> Response:
    return Response(status_code=200, media_type="text/html")


@app.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    return HTMLResponse(PRIVACY_POLICY_HTML)


@app.get("/api/bot/summary")
async def bot_summary() -> dict[str, object]:
    async with inflight_lock:
        inflight_count = len(inflight_tasks)
    return {
        "bot": {
            "name": "TTSmodachi",
            "clientId": main_bot_client_id,
            "inviteUrl": discord_invite_url(main_bot_client_id, main_bot_invite_permissions),
            "secondBotInviteUrl": second_bot_invite_url
            or discord_invite_url(second_bot_client_id, second_bot_invite_permissions),
            "supportUrl": support_invite_url,
            "permissionInteger": main_bot_invite_permissions,
        },
        "analytics": storage_for().get_public_bot_analytics(),
        "renderer": {
            "inflightRenders": inflight_count,
            "maxInflightRenders": max_inflight_renders,
            "pool": pool.health() if pool else None,
        },
    }


@app.get("/api/config")
async def config(request: Request) -> dict[str, object]:
    require_panel_token(request)
    return {
        "builtins": {name: voice.to_dict() for name, voice in BUILTIN_VOICES.items()},
        "engines": {engine_id: info.__dict__ for engine_id, info in ENGINES.items()},
        "languages": supported_languages(),
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
    display_name, avatar_url = store.get_panel_account_profile(panel_session.user_id)
    voice = coerce_supported_voice(store.resolve_voice(effective_voice_id, panel_session.guild_id, panel_session.user_id))
    return {
        "guildId": panel_session.guild_id,
        "userId": panel_session.user_id,
        "displayName": panel_session.display_name or display_name,
        "avatarUrl": panel_session.avatar_url or avatar_url,
        "voiceId": effective_voice_id,
        "voice": voice.to_dict(),
        "expiresAt": panel_session.expires_at,
    }


@app.post("/api/voice/save")
async def save_voice(request: Request, payload: SaveVoiceRequest) -> dict[str, object]:
    panel_session = require_panel_session(request)
    try:
        voice = VoiceParams.from_mapping(payload.voice)
        require_supported_voice_language(voice)
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
        voice = coerce_supported_voice(VoiceParams.from_mapping(payload.voice))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    text = payload.text.replace("\n", " ").strip()
    if len(text) > voice.text_limit():
        raise HTTPException(status_code=400, detail=f"Text is longer than {voice.text_limit()} characters")
    render_text = add_grammar_pauses(text) if grammar_pauses and payload.mode == "text" else text

    key = cache_key(render_text, voice, payload.mode, f"{engine_version}:gain{output_gain_percent}:grammarpauses1")
    store = storage_for()
    store.increment_counter("render_requests")

    cache_path = cache_dir / f"{key}.wav"
    if cache_path.exists():
        store.increment_counter("render_cache_hit")
        return FileResponse(cache_path, media_type="audio/wav", filename="speech.wav", headers={"X-Cache": "HIT"})

    created = False
    async with inflight_lock:
        task = inflight_tasks.get(key)
        if task is None:
            if len(inflight_tasks) >= max_inflight_renders:
                raise HTTPException(status_code=429, detail="Renderer queue is full")
            task = asyncio.create_task(_render_to_cache(cache_path, render_text, voice, payload.mode))
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
    store.increment_counter(f"render_cache_{cache_header.lower()}")
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
        audio = amplify_wav(result["audio"], effective_output_volume(voice))
        with NamedTemporaryFile(dir=cache_dir, delete=False) as temp:
            temp.write(audio)
            temp_path = Path(temp.name)
        temp_path.replace(cache_path)
        schedule_cache_prune()
        return {"cache": "MISS", "elapsed_ms": result.get("elapsed_ms", "")}


def schedule_cache_prune() -> None:
    global cache_prune_next_at, cache_prune_task
    if cache_max_bytes <= 0:
        return
    now = time.monotonic()
    if cache_prune_task is not None and not cache_prune_task.done():
        return
    if cache_prune_interval_seconds > 0 and now < cache_prune_next_at:
        return
    cache_prune_next_at = now + max(cache_prune_interval_seconds, 0)
    cache_prune_task = asyncio.create_task(_prune_cache_background())


def effective_output_volume(voice: VoiceParams) -> int:
    return max(25, min(300, round(voice.volume * output_gain_percent / 100)))


async def _prune_cache_background() -> None:
    try:
        await asyncio.to_thread(prune_cache)
    except Exception:
        LOGGER.warning("Cache prune failed", exc_info=True)


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
        panel_session = parse_panel_token(token)
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    linked_at_ms = storage_for().get_panel_account_linked_at_ms(panel_session.user_id)
    if linked_at_ms is None or panel_session.issued_at_ms < linked_at_ms:
        raise HTTPException(status_code=401, detail="Use /voice to link your account first!")
    return panel_session


def storage_for() -> Storage:
    if storage is None:
        raise HTTPException(status_code=503, detail="Storage is not ready")
    return storage


def configured_worker_roms() -> set[str]:
    if pool is not None:
        workers = (pool.health() or {}).get("workers") or []
        roms = {str(worker.get("rom", "")).upper() for worker in workers if worker.get("rom")}
        if roms:
            return roms
    return {
        rom.strip().upper()
        for rom in (env_value("TTSMODACHI_WORKER_ROMS", "US") or "US").split(",")
        if rom.strip()
    }


def supported_languages() -> list[str]:
    roms = configured_worker_roms()
    languages = [lang for lang, rom in LANG_TO_ROM.items() if rom.upper() in roms]
    return languages or ["useng"]


def coerce_supported_voice(voice: VoiceParams) -> VoiceParams:
    languages = supported_languages()
    if voice.lang in languages:
        return voice
    return replace(voice, lang=languages[0])


def require_supported_voice_language(voice: VoiceParams) -> None:
    languages = supported_languages()
    if voice.lang in languages:
        return
    raise ValueError(
        f"Language {voice.lang} needs a ROM this bot does not have right now. Available: {', '.join(languages)}"
    )


def is_public_request(request: Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    return bool(host and host in public_hosts)


def discord_invite_url(client_id: str | None, permissions: int) -> str | None:
    if not client_id:
        return None
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "permissions": str(permissions),
            "scope": "bot applications.commands",
        }
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("RENDERER_HOST", "0.0.0.0")
    port = int(os.environ.get("RENDERER_PORT", "8080"))
    uvicorn.run("ttsmodachi_bot.renderer_service:app", host=host, port=port)


if __name__ == "__main__":
    main()

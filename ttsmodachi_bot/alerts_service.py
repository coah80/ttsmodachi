from __future__ import annotations

import asyncio
import hmac
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .alerts import AlertEvent, RecentEventIds, alert_matches, build_speech_text, normalize_alert, parse_alert_types
from .env import env_int, env_value
from .message_cleaner import clean_message
from .render_client import RendererClient
from .voices import BUILTIN_VOICES, VoiceParams


LOGGER = logging.getLogger(__name__)
AUDIO_ID_RE = re.compile(r"^[a-f0-9-]{32,40}$", re.IGNORECASE)


def default_install_id() -> str:
    configured = env_value("TTSMODACHI_ALERTS_INSTALL_ID", "") or ""
    if configured:
        return configured
    secret = env_value("TTSMODACHI_ALERTS_SHARED_SECRET", "") or ""
    if secret:
        return f"se-{sha256(secret.encode('utf-8')).hexdigest()[:16]}"
    return "default"


class AlertState:
    def __init__(self) -> None:
        self.renderer = RendererClient(env_value("RENDERER_URL", "http://127.0.0.1:18080") or "http://127.0.0.1:18080")
        self.voice = self.load_voice()
        self.allowed_types = parse_alert_types(env_value("TTSMODACHI_ALERTS_INCLUDE_TYPES"))
        self.recent = RecentEventIds(env_int("TTSMODACHI_ALERTS_DEDUPE_SECONDS", 90))
        self.cache_dir = Path(env_value("TTSMODACHI_ALERTS_CACHE_DIR", ".alerts-cache") or ".alerts-cache")
        self.audio_ttl_seconds = env_int("TTSMODACHI_ALERTS_AUDIO_TTL_SECONDS", 600)
        self.audio_max_files = env_int("TTSMODACHI_ALERTS_AUDIO_MAX_FILES", 80)
        self.message_template = env_value("TTSMODACHI_ALERTS_MESSAGE_TEMPLATE")
        self.no_message_template = env_value("TTSMODACHI_ALERTS_NO_MESSAGE_TEMPLATE")
        self.public_base_url = (env_value("TTSMODACHI_ALERTS_PUBLIC_BASE_URL", "") or "").rstrip("/")
        self.install_id = default_install_id()
        self.install_voices = self.load_install_voices()
        self.skip_emoji = (env_value("TTSMODACHI_ALERTS_SKIP_EMOJI", "false") or "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.repeated_chars = env_int("TTSMODACHI_ALERTS_REPEATED_CHARS", 8)
        self.render_lock = asyncio.Lock()
        self.last_event: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.stats = {
            "received": 0,
            "rendered": 0,
            "skipped": 0,
            "duplicates": 0,
            "failed": 0,
        }

    async def start(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def stop(self) -> None:
        await self.renderer.close()

    def load_voice(self) -> VoiceParams:
        voice_name = env_value("TTSMODACHI_ALERTS_VOICE", "youngf") or "youngf"
        voice_json = env_value("TTSMODACHI_ALERTS_VOICE_JSON")
        if voice_json:
            try:
                return VoiceParams.from_mapping(json.loads(voice_json))
            except (ValueError, json.JSONDecodeError):
                LOGGER.warning("Invalid TTSMODACHI_ALERTS_VOICE_JSON; using %s", voice_name)
        return BUILTIN_VOICES.get(voice_name, BUILTIN_VOICES["youngf"])

    def load_install_voices(self) -> dict[str, VoiceParams]:
        raw = env_value("TTSMODACHI_ALERTS_INSTALL_VOICES_JSON")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("Invalid TTSMODACHI_ALERTS_INSTALL_VOICES_JSON; ignoring install voice map")
            return {}
        if not isinstance(data, dict):
            LOGGER.warning("TTSMODACHI_ALERTS_INSTALL_VOICES_JSON must be an object")
            return {}
        voices: dict[str, VoiceParams] = {}
        for install_id, value in data.items():
            key = str(install_id).strip()
            if not key:
                continue
            try:
                if isinstance(value, str):
                    voice = BUILTIN_VOICES.get(value)
                    if voice is not None:
                        voices[key] = voice
                elif isinstance(value, dict):
                    params = value.get("params")
                    voice_name = str(value.get("voice") or "").strip()
                    if isinstance(params, dict):
                        voices[key] = VoiceParams.from_mapping(params)
                    elif voice_name:
                        voice = BUILTIN_VOICES.get(voice_name)
                        if voice is not None:
                            voices[key] = voice
                        else:
                            LOGGER.warning("Unknown install voice %s for %s; ignoring it", voice_name, key)
                    else:
                        voices[key] = VoiceParams.from_mapping(value)
            except (TypeError, ValueError):
                LOGGER.warning("Invalid install voice for %s; ignoring it", key)
        return voices

    def voice_for(self, install_id: str) -> VoiceParams:
        return self.install_voices.get(install_id) or self.voice

    async def render_raw(self, payload: dict[str, Any], source: str, request: Request) -> dict[str, Any]:
        self.stats["received"] += 1
        alert = normalize_alert(payload, source)
        if not alert_matches(alert, self.allowed_types):
            self.stats["skipped"] += 1
            return {"ok": True, "rendered": False, "reason": "ignored_event_type", "event": alert.public_dict()}
        if self.recent.seen(alert.id):
            self.stats["duplicates"] += 1
            return {"ok": True, "rendered": False, "reason": "duplicate", "event": alert.public_dict()}

        text = self.speech_text(alert)
        if not text:
            self.stats["skipped"] += 1
            return {"ok": True, "rendered": False, "reason": "empty_text", "event": alert.public_dict()}
        voice = self.voice_for(alert.install_id)

        try:
            async with self.render_lock:
                audio = await self.renderer.render(text, voice)
                audio_id = uuid.uuid4().hex
                audio_path = self.cache_dir / f"{audio_id}.wav"
                await asyncio.to_thread(audio_path.write_bytes, audio)
                await asyncio.to_thread(self.prune_audio)
        except Exception as error:
            self.stats["failed"] += 1
            self.last_error = str(error)
            LOGGER.warning("Alert render failed", exc_info=True)
            raise HTTPException(status_code=502, detail=str(error)) from error

        self.stats["rendered"] += 1
        self.last_event = alert.public_dict()
        self.last_error = None
        audio_url = f"/audio/{audio_id}.wav"
        return {
            "ok": True,
            "rendered": True,
            "audioUrl": absolute_url(request, audio_url, self.public_base_url),
            "event": alert.public_dict(),
            "text": text,
            "voice": voice.to_dict(),
            "readyAt": time.time(),
        }

    async def render_test(self, payload: dict[str, Any], request: Request) -> dict[str, Any]:
        event = {
            "listener": payload.get("listener") or "cheer-latest",
            "installId": payload.get("installId") or self.install_id,
            "channel": {"username": payload.get("channel") or "manual-test"},
            "event": {
                "id": uuid.uuid4().hex,
                "name": payload.get("user") or "test user",
                "amount": payload.get("amount") or 100,
                "message": payload.get("message") or "this is a test bit message",
            },
        }
        return await self.render_raw(event, "manual-test", request)

    def speech_text(self, alert: AlertEvent) -> str:
        text = build_speech_text(alert, self.message_template, self.no_message_template)
        return clean_message(
            text,
            skip_emoji=self.skip_emoji,
            repeated_chars=self.repeated_chars,
        )

    def prune_audio(self) -> None:
        now = time.time()
        entries: list[tuple[float, Path]] = []
        for path in self.cache_dir.glob("*.wav"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if self.audio_ttl_seconds > 0 and stat.st_mtime < now - self.audio_ttl_seconds:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            entries.append((stat.st_mtime, path))
        if len(entries) <= self.audio_max_files:
            return
        for _, path in sorted(entries)[: len(entries) - self.audio_max_files]:
            try:
                path.unlink()
            except OSError:
                pass

    def status(self, request: Request | None = None) -> dict[str, Any]:
        base_url = self.public_base_url
        if request is not None and not base_url:
            base_url = str(request.base_url).rstrip("/")
        return {
            "ok": True,
            "rendererUrl": self.renderer.base_url,
            "setupUrl": f"{base_url}/setup" if base_url else "/setup",
            "endpointUrl": f"{base_url}/api/alerts/streamelements" if base_url else "/api/alerts/streamelements",
            "installId": self.install_id,
            "voice": self.voice.to_dict(),
            "installVoiceIds": sorted(self.install_voices),
            "allowedTypes": sorted(self.allowed_types),
            "lastEvent": self.last_event,
            "lastError": self.last_error,
            "stats": self.stats,
        }


mimetypes.add_type("text/javascript", ".js")

state = AlertState()
app = FastAPI(title="TTSmodachi StreamElements Alerts", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in (env_value("TTSMODACHI_ALERTS_CORS_ORIGINS", "*") or "*").split(",")],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

web_dir = Path(__file__).resolve().parents[1] / "web" / "alerts"
widget_path = Path(__file__).resolve().parents[1] / "streamelements" / "ttsmodachi-widget.js"
alertbox_html_path = Path(__file__).resolve().parents[1] / "streamelements" / "alertbox" / "ttsmodachi-alertbox.html"
alertbox_js_path = Path(__file__).resolve().parents[1] / "streamelements" / "alertbox" / "ttsmodachi-alertbox.js"
app.mount("/assets", StaticFiles(directory=web_dir), name="alert-assets")


@app.on_event("startup")
async def startup() -> None:
    await state.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await state.stop()


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/setup")


@app.get("/setup", response_class=HTMLResponse)
async def setup_page() -> FileResponse:
    return FileResponse(web_dir / "setup.html", media_type="text/html")


@app.get("/widget.js", response_class=PlainTextResponse)
async def widget_script() -> PlainTextResponse:
    return PlainTextResponse(widget_path.read_text(encoding="utf-8"), media_type="text/javascript")


@app.get("/audio/{audio_id}.wav")
async def alert_audio(audio_id: str) -> FileResponse:
    if not AUDIO_ID_RE.fullmatch(audio_id):
        raise HTTPException(status_code=404, detail="Audio not found")
    path = state.cache_dir / f"{audio_id}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/wav", filename="ttsmodachi-alert.wav")


@app.get("/api/alerts/status")
async def alert_status(request: Request) -> dict[str, Any]:
    return state.status(request)


@app.get("/api/alerts/widget-code")
async def widget_code(request: Request) -> dict[str, str]:
    endpoint = state.status(request)["endpointUrl"]
    secret = env_value("TTSMODACHI_ALERTS_SHARED_SECRET", "") or ""
    source = widget_path.read_text(encoding="utf-8")
    source = source.replace("%%TTSMODACHI_ENDPOINT%%", endpoint)
    source = source.replace("%%TTSMODACHI_TOKEN%%", secret)
    source = source.replace("%%TTSMODACHI_INSTALL_ID%%", state.install_id)
    return {"code": source, "installId": state.install_id}


@app.get("/api/alerts/alertbox-code")
async def alertbox_code(request: Request) -> dict[str, str]:
    endpoint = state.status(request)["endpointUrl"]
    secret = env_value("TTSMODACHI_ALERTS_SHARED_SECRET", "") or ""
    channel = env_value("TTSMODACHI_ALERTS_CHANNEL", "") or ""
    listener = env_value("TTSMODACHI_ALERTS_ALERTBOX_LISTENER", "cheer-latest") or "cheer-latest"
    html = alertbox_html_path.read_text(encoding="utf-8")
    script = alertbox_js_path.read_text(encoding="utf-8")
    script = script.replace("%%TTSMODACHI_ENDPOINT%%", endpoint)
    script = script.replace("%%TTSMODACHI_TOKEN%%", secret)
    script = script.replace("%%TTSMODACHI_INSTALL_ID%%", state.install_id)
    script = script.replace("%%TTSMODACHI_CHANNEL%%", channel)
    script = script.replace("%%TTSMODACHI_LISTENER%%", listener)
    return {"html": html, "js": script, "installId": state.install_id, "listener": listener}


@app.post("/api/alerts/streamelements")
async def streamelements_alert(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    require_alert_secret(request, payload)
    return await state.render_raw(payload, "streamelements-widget", request)


@app.post("/api/alerts/test")
async def test_alert(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    require_alert_secret(request, payload)
    return await state.render_test(payload, request)


async def read_json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Invalid JSON") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    return payload


def require_alert_secret(request: Request, payload: dict[str, Any]) -> None:
    secret = env_value("TTSMODACHI_ALERTS_SHARED_SECRET")
    if not secret:
        return
    supplied = (
        request.headers.get("x-alert-token")
        or request.query_params.get("token")
        or str(payload.get("token") or "")
    )
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(status_code=401, detail="Alert token required")


def absolute_url(request: Request, path: str, configured_base: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = configured_base or str(request.base_url).rstrip("/")
    return f"{base}{path}"


def main() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    host = env_value("TTSMODACHI_ALERTS_BIND", "0.0.0.0") or "0.0.0.0"
    port = env_int("TTSMODACHI_ALERTS_PORT", 8081)
    uvicorn.run("ttsmodachi_bot.alerts_service:app", host=host, port=port)


if __name__ == "__main__":
    main()

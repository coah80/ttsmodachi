from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .alerts import RecentEventIds, alert_matches, build_speech_text, normalize_alert, parse_alert_types
from .env import env_int, env_value
from .message_cleaner import clean_message
from .render_client import RendererClient
from .voices import BUILTIN_VOICES, VoiceParams


LOGGER = logging.getLogger(__name__)
SESSION_COOKIE = "ttsmodachi_stream_session"
OAUTH_STATE_COOKIE = "ttsmodachi_stream_oauth_state"
AUDIO_ID_RE = re.compile(r"^[a-f0-9]{32}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
STREAM_RANDOM_VOICE_DEFAULT = "deepm,adultm,youngm,adultf,highf,tinyf,oldm,oldf"
STREAM_RANDOM_VOICE_PRESETS: dict[str, VoiceParams] = {
    "deepm": VoiceParams(accent=22, intonation=1, pitch=15, quality=34, speed=46, tone=18, volume=200),
    "adultm": VoiceParams(accent=25, intonation=1, pitch=31, quality=39, speed=52, tone=25, volume=190),
    "youngm": VoiceParams(accent=25, intonation=1, pitch=60, quality=72, speed=59, tone=25, volume=190),
    "adultf": VoiceParams(accent=25, intonation=1, pitch=68, quality=58, speed=39, tone=25, volume=190),
    "youngf": VoiceParams(accent=25, intonation=1, pitch=83, quality=78, speed=65, tone=25, volume=190),
    "highf": VoiceParams(accent=25, intonation=1, pitch=94, quality=82, speed=70, tone=32, volume=195),
    "tinyf": VoiceParams(accent=28, intonation=1, pitch=100, quality=88, speed=76, tone=38, volume=200),
    "oldm": VoiceParams(accent=25, intonation=1, pitch=25, quality=39, speed=29, tone=15, volume=195),
    "oldf": VoiceParams(accent=42, intonation=1, pitch=67, quality=69, speed=18, tone=12, volume=195),
}


@dataclass(frozen=True)
class Streamer:
    broadcaster_id: str
    login: str
    display_name: str
    profile_image_url: str
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str
    overlay_key: str
    session_token: str
    updated_at: int


class StreamStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()
        self.setup()

    def setup(self) -> None:
        self.connection.executescript(
            """
            create table if not exists streamers (
                broadcaster_id text primary key,
                login text not null,
                display_name text not null,
                profile_image_url text not null default '',
                access_token text not null,
                refresh_token text not null,
                expires_at integer not null,
                scope text not null default '',
                overlay_key text not null unique,
                session_token text not null unique,
                created_at integer not null,
                updated_at integer not null
            );
            create table if not exists stream_settings (
                broadcaster_id text primary key,
                enabled integer not null default 1,
                min_bits integer not null default 1,
                include_username integer not null default 1,
                random_voice integer not null default 1,
                voice text not null default 'youngf',
                message_template text not null default '{user} cheered {amount} bits. {message}',
                no_message_template text not null default '{user} cheered {amount} bits.',
                foreign key (broadcaster_id) references streamers(broadcaster_id)
            );
            create table if not exists stream_events (
                id text primary key,
                broadcaster_id text not null,
                user text not null,
                amount integer not null,
                message text not null,
                spoken_text text not null,
                voice text not null,
                audio_id text,
                created_at integer not null,
                foreign key (broadcaster_id) references streamers(broadcaster_id)
            );
            """
        )
        columns = {
            str(row["name"])
            for row in self.connection.execute("pragma table_info(stream_settings)").fetchall()
        }
        if "speech_delay_ms" not in columns:
            self.connection.execute(
                "alter table stream_settings add column speech_delay_ms integer not null default 1500"
            )
        self.connection.commit()

    async def close(self) -> None:
        async with self.lock:
            self.connection.close()

    async def upsert_streamer(self, profile: dict[str, Any], token: dict[str, Any]) -> Streamer:
        now = int(time.time())
        broadcaster_id = str(profile["id"])
        existing = await self.get_streamer(broadcaster_id)
        overlay_key = existing.overlay_key if existing else make_public_key()
        session_token = existing.session_token if existing else secrets.token_urlsafe(32)
        refresh_token = str(token.get("refresh_token") or (existing.refresh_token if existing else ""))
        scopes = token.get("scope") or []
        expires_at = now + int(token.get("expires_in") or 0)
        async with self.lock:
            self.connection.execute(
                """
                insert into streamers (
                    broadcaster_id, login, display_name, profile_image_url,
                    access_token, refresh_token, expires_at, scope,
                    overlay_key, session_token, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(broadcaster_id) do update set
                    login=excluded.login,
                    display_name=excluded.display_name,
                    profile_image_url=excluded.profile_image_url,
                    access_token=excluded.access_token,
                    refresh_token=case when excluded.refresh_token != '' then excluded.refresh_token else streamers.refresh_token end,
                    expires_at=excluded.expires_at,
                    scope=excluded.scope,
                    session_token=excluded.session_token,
                    updated_at=excluded.updated_at
                """,
                (
                    broadcaster_id,
                    str(profile.get("login") or ""),
                    str(profile.get("display_name") or profile.get("login") or ""),
                    str(profile.get("profile_image_url") or ""),
                    str(token["access_token"]),
                    refresh_token,
                    expires_at,
                    " ".join(str(scope) for scope in scopes),
                    overlay_key,
                    session_token,
                    now,
                    now,
                ),
            )
            self.connection.execute(
                "insert or ignore into stream_settings (broadcaster_id) values (?)",
                (broadcaster_id,),
            )
            self.connection.commit()
        streamer = await self.get_streamer(broadcaster_id)
        if streamer is None:
            raise RuntimeError("Streamer was not saved")
        return streamer

    async def update_token(self, streamer: Streamer, token: dict[str, Any]) -> Streamer:
        expires_at = int(time.time()) + int(token.get("expires_in") or 0)
        refresh_token = str(token.get("refresh_token") or streamer.refresh_token)
        async with self.lock:
            self.connection.execute(
                """
                update streamers set access_token=?, refresh_token=?, expires_at=?, updated_at=?
                where broadcaster_id=?
                """,
                (
                    str(token["access_token"]),
                    refresh_token,
                    expires_at,
                    int(time.time()),
                    streamer.broadcaster_id,
                ),
            )
            self.connection.commit()
        refreshed = await self.get_streamer(streamer.broadcaster_id)
        if refreshed is None:
            raise RuntimeError("Streamer disappeared after token refresh")
        return refreshed

    async def get_streamer(self, broadcaster_id: str) -> Streamer | None:
        async with self.lock:
            row = self.connection.execute(
                "select * from streamers where broadcaster_id=?",
                (broadcaster_id,),
            ).fetchone()
        return streamer_from_row(row)

    async def get_by_session(self, session_token: str) -> Streamer | None:
        async with self.lock:
            row = self.connection.execute(
                "select * from streamers where session_token=?",
                (session_token,),
            ).fetchone()
        return streamer_from_row(row)

    async def get_by_overlay_key(self, overlay_key: str) -> Streamer | None:
        async with self.lock:
            row = self.connection.execute(
                "select * from streamers where overlay_key=?",
                (overlay_key,),
            ).fetchone()
        return streamer_from_row(row)

    async def list_streamers(self) -> list[Streamer]:
        async with self.lock:
            rows = self.connection.execute("select * from streamers order by updated_at desc").fetchall()
        return [streamer for row in rows if (streamer := streamer_from_row(row)) is not None]

    async def settings(self, broadcaster_id: str) -> dict[str, Any]:
        async with self.lock:
            row = self.connection.execute(
                "select * from stream_settings where broadcaster_id=?",
                (broadcaster_id,),
            ).fetchone()
        if row is None:
            return default_settings()
        return {
            "enabled": bool(row["enabled"]),
            "minBits": int(row["min_bits"]),
            "includeUsername": bool(row["include_username"]),
            "randomVoice": bool(row["random_voice"]),
            "voice": str(row["voice"]),
            "speechDelayMs": int(row["speech_delay_ms"]),
            "messageTemplate": str(row["message_template"]),
            "noMessageTemplate": str(row["no_message_template"]),
        }

    async def update_settings(self, broadcaster_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = await self.settings(broadcaster_id)
        settings = {
            "enabled": bool(payload.get("enabled", current["enabled"])),
            "minBits": max(1, min(1_000_000, int(payload.get("minBits", current["minBits"])))),
            "includeUsername": bool(payload.get("includeUsername", current["includeUsername"])),
            "randomVoice": bool(payload.get("randomVoice", current["randomVoice"])),
            "voice": str(payload.get("voice", current["voice"])),
            "speechDelayMs": max(0, min(30_000, int(payload.get("speechDelayMs", current["speechDelayMs"])))),
            "messageTemplate": str(payload.get("messageTemplate", current["messageTemplate"])).strip()
            or current["messageTemplate"],
            "noMessageTemplate": str(payload.get("noMessageTemplate", current["noMessageTemplate"])).strip()
            or current["noMessageTemplate"],
        }
        if settings["voice"] not in BUILTIN_VOICES:
            settings["voice"] = "youngf"
        async with self.lock:
            self.connection.execute(
                """
                insert into stream_settings (
                    broadcaster_id, enabled, min_bits, include_username,
                    random_voice, voice, speech_delay_ms, message_template, no_message_template
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(broadcaster_id) do update set
                    enabled=excluded.enabled,
                    min_bits=excluded.min_bits,
                    include_username=excluded.include_username,
                    random_voice=excluded.random_voice,
                    voice=excluded.voice,
                    speech_delay_ms=excluded.speech_delay_ms,
                    message_template=excluded.message_template,
                    no_message_template=excluded.no_message_template
                """,
                (
                    broadcaster_id,
                    int(settings["enabled"]),
                    settings["minBits"],
                    int(settings["includeUsername"]),
                    int(settings["randomVoice"]),
                    settings["voice"],
                    settings["speechDelayMs"],
                    settings["messageTemplate"],
                    settings["noMessageTemplate"],
                ),
            )
            self.connection.commit()
        return settings

    async def regenerate_overlay_key(self, broadcaster_id: str) -> Streamer:
        overlay_key = make_public_key()
        async with self.lock:
            self.connection.execute(
                "update streamers set overlay_key=?, updated_at=? where broadcaster_id=?",
                (overlay_key, int(time.time()), broadcaster_id),
            )
            self.connection.commit()
        streamer = await self.get_streamer(broadcaster_id)
        if streamer is None:
            raise RuntimeError("Streamer disappeared after overlay key regeneration")
        return streamer

    async def save_event(self, event: dict[str, Any]) -> None:
        async with self.lock:
            self.connection.execute(
                """
                insert or replace into stream_events (
                    id, broadcaster_id, user, amount, message, spoken_text,
                    voice, audio_id, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["broadcasterId"],
                    event["user"],
                    event["amount"],
                    event["message"],
                    event["spokenText"],
                    event["voice"],
                    event.get("audioId"),
                    int(event["createdAt"]),
                ),
            )
            self.connection.commit()

    async def recent_events(self, broadcaster_id: str, limit: int = 10) -> list[dict[str, Any]]:
        async with self.lock:
            rows = self.connection.execute(
                """
                select * from stream_events
                where broadcaster_id=?
                order by created_at desc
                limit ?
                """,
                (broadcaster_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "user": row["user"],
                "amount": row["amount"],
                "message": row["message"],
                "spokenText": row["spoken_text"],
                "voice": row["voice"],
                "audioId": row["audio_id"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


class TwitchClient:
    def __init__(self) -> None:
        self.client_id = env_value("TWITCH_CLIENT_ID", "") or ""
        self.client_secret = env_value("TWITCH_CLIENT_SECRET", "") or ""
        self.scope = env_value("TTSMODACHI_STREAM_TWITCH_SCOPE", "bits:read") or "bits:read"
        self.session: aiohttp.ClientSession | None = None

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    def session_for(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": self.scope,
                "state": state,
            }
        )
        return f"https://id.twitch.tv/oauth2/authorize?{query}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        return await self.post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self.post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    async def post_token(self, data: dict[str, str]) -> dict[str, Any]:
        async with self.session_for().post(
            "https://id.twitch.tv/oauth2/token",
            data=data,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise HTTPException(status_code=502, detail={"twitch": payload})
            return payload

    async def user_profile(self, access_token: str) -> dict[str, Any]:
        async with self.session_for().get(
            "https://api.twitch.tv/helix/users",
            headers=self.headers(access_token),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise HTTPException(status_code=502, detail={"twitch": payload})
            data = payload.get("data") or []
            if not data:
                raise HTTPException(status_code=502, detail="Twitch did not return a user profile")
            return data[0]

    async def subscribe_cheer(self, access_token: str, broadcaster_id: str, session_id: str) -> None:
        body = {
            "type": "channel.cheer",
            "version": "1",
            "condition": {"broadcaster_user_id": broadcaster_id},
            "transport": {"method": "websocket", "session_id": session_id},
        }
        async with self.session_for().post(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers=self.headers(access_token),
            json=body,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            payload = await response.json(content_type=None)
            if response.status not in {200, 202, 409}:
                raise RuntimeError(f"Twitch EventSub subscribe failed {response.status}: {payload}")

    def headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": self.client_id,
            "Content-Type": "application/json",
        }


class BroadcastHub:
    def __init__(self) -> None:
        self.listeners: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.lock = asyncio.Lock()

    async def subscribe(self, key: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        async with self.lock:
            self.listeners.setdefault(key, set()).add(queue)
        return queue

    async def unsubscribe(self, key: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self.lock:
            queues = self.listeners.get(key)
            if not queues:
                return
            queues.discard(queue)
            if not queues:
                self.listeners.pop(key, None)

    async def publish(self, key: str, event: dict[str, Any]) -> None:
        async with self.lock:
            queues = list(self.listeners.get(key) or [])
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def counts(self) -> dict[str, int]:
        async with self.lock:
            return {key: len(value) for key, value in self.listeners.items()}


class EventSubManager:
    def __init__(self, state: "StreamState") -> None:
        self.state = state
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.stop_event = asyncio.Event()

    async def start_all(self) -> None:
        if not self.state.twitch.configured():
            return
        for streamer in await self.state.store.list_streamers():
            await self.ensure(streamer)

    async def stop(self) -> None:
        self.stop_event.set()
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def ensure(self, streamer: Streamer) -> None:
        task = self.tasks.get(streamer.broadcaster_id)
        if task is not None and not task.done():
            return
        self.tasks[streamer.broadcaster_id] = asyncio.create_task(self.run(streamer.broadcaster_id))

    def public_status(self, broadcaster_id: str) -> dict[str, Any]:
        return self.status.get(
            broadcaster_id,
            {"connected": False, "detail": "not connected", "updatedAt": int(time.time())},
        )

    async def run(self, broadcaster_id: str) -> None:
        backoff = 2
        while not self.stop_event.is_set():
            streamer = await self.state.store.get_streamer(broadcaster_id)
            if streamer is None:
                return
            try:
                streamer = await self.state.fresh_streamer(streamer)
                await self.connect(streamer)
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOGGER.warning("EventSub connection failed for %s", broadcaster_id, exc_info=True)
                self.status[broadcaster_id] = {
                    "connected": False,
                    "detail": str(error),
                    "updatedAt": int(time.time()),
                }
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def connect(self, streamer: Streamer) -> None:
        url = "wss://eventsub.wss.twitch.tv/ws"
        subscribed = False
        async with self.state.twitch.session_for().ws_connect(url, heartbeat=20) as ws:
            async for message in ws:
                if message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                payload = json.loads(message.data)
                metadata = payload.get("metadata") or {}
                message_type = metadata.get("message_type")
                if message_type == "session_welcome":
                    session_id = (((payload.get("payload") or {}).get("session") or {}).get("id")) or ""
                    if not session_id:
                        raise RuntimeError("Twitch did not send a WebSocket session id")
                    await self.state.twitch.subscribe_cheer(streamer.access_token, streamer.broadcaster_id, session_id)
                    subscribed = True
                    self.status[streamer.broadcaster_id] = {
                        "connected": True,
                        "detail": "listening for cheers",
                        "updatedAt": int(time.time()),
                    }
                elif message_type == "session_keepalive":
                    if subscribed:
                        self.status[streamer.broadcaster_id] = {
                            "connected": True,
                            "detail": "listening for cheers",
                            "updatedAt": int(time.time()),
                        }
                elif message_type == "notification":
                    event = ((payload.get("payload") or {}).get("event") or {})
                    await self.state.handle_cheer(streamer.broadcaster_id, event)
                elif message_type == "session_reconnect":
                    break
                elif message_type == "revocation":
                    self.status[streamer.broadcaster_id] = {
                        "connected": False,
                        "detail": "Twitch revoked the EventSub subscription",
                        "updatedAt": int(time.time()),
                    }
                    await asyncio.sleep(10)
                    break


class StreamState:
    def __init__(self) -> None:
        data_dir = Path(env_value("TTSMODACHI_STREAM_DATA_DIR", "/data/stream") or "/data/stream")
        self.public_base_url = (env_value("TTSMODACHI_STREAM_PUBLIC_BASE_URL", "") or "").rstrip("/")
        self.store = StreamStore(data_dir / "stream.sqlite3")
        self.audio_dir = Path(env_value("TTSMODACHI_STREAM_AUDIO_DIR", str(data_dir / "audio")) or str(data_dir / "audio"))
        self.audio_ttl_seconds = env_int("TTSMODACHI_STREAM_AUDIO_TTL_SECONDS", 900)
        self.audio_max_files = env_int("TTSMODACHI_STREAM_AUDIO_MAX_FILES", 200)
        self.cookie_secret = env_value("TTSMODACHI_STREAM_COOKIE_SECRET", "") or "dev-cookie-secret"
        self.renderer = RendererClient(env_value("RENDERER_URL", "http://127.0.0.1:18080") or "http://127.0.0.1:18080")
        self.twitch = TwitchClient()
        self.hub = BroadcastHub()
        self.eventsub = EventSubManager(self)
        self.render_lock = asyncio.Lock()
        self.se_secret = env_value("TTSMODACHI_STREAM_SE_SECRET", env_value("TTSMODACHI_ALERTS_SHARED_SECRET", "")) or ""
        self.se_install_id = stream_elements_install_id(self.se_secret)
        self.se_channel = env_value("TTSMODACHI_STREAM_SE_CHANNEL", env_value("TTSMODACHI_ALERTS_CHANNEL", "")) or ""
        self.se_listener = env_value(
            "TTSMODACHI_STREAM_SE_LISTENER",
            env_value("TTSMODACHI_ALERTS_ALERTBOX_LISTENER", "cheer-latest"),
        ) or "cheer-latest"
        include_types = env_value(
            "TTSMODACHI_STREAM_SE_INCLUDE_TYPES",
            env_value("TTSMODACHI_ALERTS_INCLUDE_TYPES", "cheer,cheer-latest,cheerPurchase,cheerPurchase-latest"),
        )
        self.se_allowed_types = parse_alert_types(include_types)
        self.se_recent = RecentEventIds(env_int("TTSMODACHI_STREAM_SE_DEDUPE_SECONDS", env_int("TTSMODACHI_ALERTS_DEDUPE_SECONDS", 90)))
        self.se_message_template = env_value(
            "TTSMODACHI_STREAM_SE_MESSAGE_TEMPLATE",
            env_value("TTSMODACHI_ALERTS_MESSAGE_TEMPLATE", "{user} cheered {amount} bits. {message}"),
        )
        self.se_no_message_template = env_value(
            "TTSMODACHI_STREAM_SE_NO_MESSAGE_TEMPLATE",
            env_value("TTSMODACHI_ALERTS_NO_MESSAGE_TEMPLATE", "{user} cheered {amount} bits."),
        )
        self.random_voice_names = [
            name.strip()
            for name in (env_value("TTSMODACHI_STREAM_RANDOM_VOICES", STREAM_RANDOM_VOICE_DEFAULT) or "").split(",")
            if name.strip() in STREAM_RANDOM_VOICE_PRESETS
        ] or list(STREAM_RANDOM_VOICE_PRESETS)
        self.last_random_voice_name = ""

    async def start(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        await self.eventsub.start_all()

    async def stop(self) -> None:
        await self.eventsub.stop()
        await self.renderer.close()
        await self.twitch.close()
        await self.store.close()

    def base_url(self, request: Request) -> str:
        return self.public_base_url or str(request.base_url).rstrip("/")

    def redirect_uri(self, request: Request) -> str:
        return f"{self.base_url(request)}/auth/twitch/callback"

    def sign(self, value: str) -> str:
        digest = hmac.new(self.cookie_secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{value}.{digest}"

    def unsign(self, signed_value: str) -> str | None:
        if "." not in signed_value:
            return None
        value, digest = signed_value.rsplit(".", 1)
        expected = hmac.new(self.cookie_secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, expected):
            return value
        return None

    async def streamer_from_request(self, request: Request) -> Streamer | None:
        signed = request.cookies.get(SESSION_COOKIE) or ""
        session_token = self.unsign(signed)
        if not session_token:
            return None
        return await self.store.get_by_session(session_token)

    async def require_streamer(self, request: Request) -> Streamer:
        streamer = await self.streamer_from_request(request)
        if streamer is None:
            raise HTTPException(status_code=401, detail="Not signed in")
        return streamer

    async def fresh_streamer(self, streamer: Streamer) -> Streamer:
        if streamer.expires_at > int(time.time()) + 120:
            return streamer
        token = await self.twitch.refresh(streamer.refresh_token)
        return await self.store.update_token(streamer, token)

    async def handle_cheer(self, broadcaster_id: str, event: dict[str, Any]) -> None:
        streamer = await self.store.get_streamer(broadcaster_id)
        if streamer is None:
            return
        settings = await self.store.settings(broadcaster_id)
        if not settings["enabled"]:
            return
        amount = int(event.get("bits") or event.get("amount") or 0)
        if amount < settings["minBits"]:
            return
        user = str(event.get("user_name") or event.get("user_login") or "someone")
        raw_message = event.get("message") or ""
        message = message_text(raw_message)
        await self.render_and_publish(
            streamer=streamer,
            event_id=str(event.get("message_id") or event.get("id") or uuid.uuid4().hex),
            user=user,
            amount=amount,
            message=message,
            settings=settings,
        )

    async def render_and_publish(
        self,
        streamer: Streamer,
        event_id: str,
        user: str,
        amount: int,
        message: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        voice_name, voice = self.pick_voice(settings)
        spoken_text = clean_message(
            format_message(user, amount, message, settings),
            skip_emoji=True,
            repeated_chars=8,
        )
        if not spoken_text:
            raise HTTPException(status_code=400, detail="Nothing to read")
        audio_id = uuid.uuid4().hex
        audio_path = self.audio_dir / f"{audio_id}.wav"
        async with self.render_lock:
            audio = await self.renderer.render(spoken_text, voice)
            await asyncio.to_thread(audio_path.write_bytes, audio)
            await asyncio.to_thread(self.prune_audio)
        payload = {
            "id": event_id,
            "broadcasterId": streamer.broadcaster_id,
            "user": user if settings["includeUsername"] else "someone",
            "amount": amount,
            "message": message,
            "spokenText": spoken_text,
            "voice": voice_name,
            "audioId": audio_id,
            "audioUrl": f"/audio/{audio_id}.wav",
            "speechDelayMs": settings["speechDelayMs"],
            "createdAt": int(time.time()),
        }
        await self.store.save_event(payload)
        await self.hub.publish(streamer.overlay_key, payload)
        return payload

    async def render_streamelements_alert(self, payload: dict[str, Any], request: Request) -> dict[str, Any]:
        alert = normalize_alert(payload, "streamelements-alertbox")
        if not alert_matches(alert, self.se_allowed_types):
            return {"ok": True, "rendered": False, "reason": "ignored_event_type", "event": alert.public_dict()}
        if self.se_recent.seen(alert.id):
            return {"ok": True, "rendered": False, "reason": "duplicate", "event": alert.public_dict()}
        spoken_text = clean_message(
            build_speech_text(alert, self.se_message_template, self.se_no_message_template),
            skip_emoji=True,
            repeated_chars=8,
        )
        if not spoken_text:
            return {"ok": True, "rendered": False, "reason": "empty_text", "event": alert.public_dict()}
        settings = default_settings()
        voice_name, voice = self.pick_voice(settings)
        audio_id = uuid.uuid4().hex
        audio_path = self.audio_dir / f"{audio_id}.wav"
        async with self.render_lock:
            audio = await self.renderer.render(spoken_text, voice)
            await asyncio.to_thread(audio_path.write_bytes, audio)
            await asyncio.to_thread(self.prune_audio)
        audio_url = f"/audio/{audio_id}.wav"
        return {
            "ok": True,
            "rendered": True,
            "audioUrl": f"{self.base_url(request)}{audio_url}",
            "event": alert.public_dict(),
            "text": spoken_text,
            "voice": voice_name,
            "readyAt": time.time(),
        }

    def pick_voice(self, settings: dict[str, Any]) -> tuple[str, VoiceParams]:
        if not settings["randomVoice"]:
            voice_name = settings["voice"]
            return voice_name, BUILTIN_VOICES.get(voice_name, BUILTIN_VOICES["youngf"])
        names = self.random_voice_names
        if len(names) > 1 and self.last_random_voice_name in names:
            names = [name for name in names if name != self.last_random_voice_name]
        voice_name = random.choice(names)
        self.last_random_voice_name = voice_name
        return voice_name, STREAM_RANDOM_VOICE_PRESETS[voice_name]

    def prune_audio(self) -> None:
        now = time.time()
        entries: list[tuple[float, Path]] = []
        for path in self.audio_dir.glob("*.wav"):
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


def streamer_from_row(row: sqlite3.Row | None) -> Streamer | None:
    if row is None:
        return None
    return Streamer(
        broadcaster_id=str(row["broadcaster_id"]),
        login=str(row["login"]),
        display_name=str(row["display_name"]),
        profile_image_url=str(row["profile_image_url"] or ""),
        access_token=str(row["access_token"]),
        refresh_token=str(row["refresh_token"]),
        expires_at=int(row["expires_at"]),
        scope=str(row["scope"] or ""),
        overlay_key=str(row["overlay_key"]),
        session_token=str(row["session_token"]),
        updated_at=int(row["updated_at"]),
    )


def default_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "minBits": 1,
        "includeUsername": True,
        "randomVoice": True,
        "voice": "youngf",
            "speechDelayMs": 1500,
        "messageTemplate": "{user} cheered {amount} bits. {message}",
        "noMessageTemplate": "{user} cheered {amount} bits.",
    }


def make_public_key() -> str:
    return secrets.token_urlsafe(32)


def stream_elements_install_id(secret: str) -> str:
    configured = env_value("TTSMODACHI_STREAM_SE_INSTALL_ID", env_value("TTSMODACHI_ALERTS_INSTALL_ID", "")) or ""
    if configured:
        return configured
    if secret:
        return f"se-{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]}"
    return "stream-elements"


def message_text(message: Any) -> str:
    if isinstance(message, dict):
        if isinstance(message.get("text"), str):
            return message["text"]
        fragments = message.get("fragments")
        if isinstance(fragments, list):
            return "".join(str(fragment.get("text") or "") for fragment in fragments if isinstance(fragment, dict))
    return str(message or "")


def format_message(user: str, amount: int, message: str, settings: dict[str, Any]) -> str:
    template = settings["messageTemplate"] if message.strip() else settings["noMessageTemplate"]
    display_user = user if settings["includeUsername"] else "someone"
    return template.format(user=display_user, amount=amount, message=message.strip())


state = StreamState()
app = FastAPI(title="TTSmodachi Stream Overlay", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in (env_value("TTSMODACHI_STREAM_CORS_ORIGINS", "*") or "*").split(",")],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
web_dir = Path(__file__).resolve().parents[1] / "web" / "stream"
alertbox_html_path = Path(__file__).resolve().parents[1] / "streamelements" / "alertbox" / "ttsmodachi-alertbox.html"
alertbox_js_path = Path(__file__).resolve().parents[1] / "streamelements" / "alertbox" / "ttsmodachi-alertbox.js"
widget_path = Path(__file__).resolve().parents[1] / "streamelements" / "ttsmodachi-widget.js"
app.mount("/assets", StaticFiles(directory=web_dir), name="stream-assets")


@app.on_event("startup")
async def startup() -> None:
    await state.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await state.stop()


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(web_dir / "dashboard.html", media_type="text/html")


@app.head("/")
async def dashboard_head() -> Response:
    return Response(status_code=200, media_type="text/html")


@app.get("/overlay/{overlay_key}")
async def overlay(overlay_key: str) -> FileResponse:
    if not KEY_RE.fullmatch(overlay_key):
        raise HTTPException(status_code=404, detail="Overlay not found")
    streamer = await state.store.get_by_overlay_key(overlay_key)
    if streamer is None:
        raise HTTPException(status_code=404, detail="Overlay not found")
    return FileResponse(web_dir / "overlay.html", media_type="text/html")


@app.get("/login")
async def login(request: Request) -> RedirectResponse:
    if not state.twitch.configured():
        raise HTTPException(status_code=503, detail="Twitch app is not configured")
    oauth_state = secrets.token_urlsafe(32)
    redirect = RedirectResponse(state.twitch.authorize_url(state.redirect_uri(request), oauth_state))
    redirect.set_cookie(
        OAUTH_STATE_COOKIE,
        state.sign(oauth_state),
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=600,
    )
    return redirect


@app.get("/auth/twitch/callback")
async def twitch_callback(request: Request) -> RedirectResponse:
    code = request.query_params.get("code") or ""
    returned_state = request.query_params.get("state") or ""
    cookie_state = state.unsign(request.cookies.get(OAUTH_STATE_COOKIE) or "")
    if not code or not returned_state or not cookie_state or not hmac.compare_digest(returned_state, cookie_state):
        raise HTTPException(status_code=400, detail="Invalid Twitch login state")
    token = await state.twitch.exchange_code(code, state.redirect_uri(request))
    profile = await state.twitch.user_profile(token["access_token"])
    streamer = await state.store.upsert_streamer(profile, token)
    await state.eventsub.ensure(streamer)
    redirect = RedirectResponse("/")
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    redirect.set_cookie(
        SESSION_COOKIE,
        state.sign(streamer.session_token),
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 180,
    )
    return redirect


@app.get("/api/alerts/alertbox-code")
async def api_alertbox_code(request: Request) -> dict[str, str]:
    endpoint = f"{state.base_url(request)}/api/alerts/streamelements"
    html = alertbox_html_path.read_text(encoding="utf-8")
    script = alertbox_js_path.read_text(encoding="utf-8")
    script = script.replace("%%TTSMODACHI_ENDPOINT%%", endpoint)
    script = script.replace("%%TTSMODACHI_TOKEN%%", state.se_secret)
    script = script.replace("%%TTSMODACHI_INSTALL_ID%%", state.se_install_id)
    script = script.replace("%%TTSMODACHI_CHANNEL%%", state.se_channel)
    script = script.replace("%%TTSMODACHI_LISTENER%%", state.se_listener)
    return {"html": html, "js": script, "installId": state.se_install_id, "listener": state.se_listener}


@app.get("/api/alerts/widget-code")
async def api_widget_code(request: Request) -> dict[str, str]:
    endpoint = f"{state.base_url(request)}/api/alerts/streamelements"
    source = widget_path.read_text(encoding="utf-8")
    source = source.replace("%%TTSMODACHI_ENDPOINT%%", endpoint)
    source = source.replace("%%TTSMODACHI_TOKEN%%", state.se_secret)
    source = source.replace("%%TTSMODACHI_INSTALL_ID%%", state.se_install_id)
    return {"code": source, "installId": state.se_install_id}


@app.post("/api/alerts/streamelements")
async def api_streamelements_alert(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    require_stream_elements_secret(request, payload)
    return await state.render_streamelements_alert(payload, request)


@app.get("/api/me")
async def api_me(request: Request) -> dict[str, Any]:
    streamer = await state.streamer_from_request(request)
    if streamer is None:
        return {
            "authenticated": False,
            "configured": state.twitch.configured(),
            "loginUrl": "/login",
        }
    settings = await state.store.settings(streamer.broadcaster_id)
    overlay_url = f"{state.base_url(request)}/overlay/{streamer.overlay_key}"
    return {
        "authenticated": True,
        "configured": state.twitch.configured(),
        "streamer": {
            "id": streamer.broadcaster_id,
            "login": streamer.login,
            "displayName": streamer.display_name,
            "profileImageUrl": streamer.profile_image_url,
            "scope": streamer.scope,
        },
        "settings": settings,
        "voices": sorted(BUILTIN_VOICES),
        "overlayUrl": overlay_url,
        "eventSub": state.eventsub.public_status(streamer.broadcaster_id),
        "recentEvents": await state.store.recent_events(streamer.broadcaster_id),
    }


@app.post("/api/settings")
async def api_settings(request: Request) -> dict[str, Any]:
    streamer = await state.require_streamer(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    settings = await state.store.update_settings(streamer.broadcaster_id, payload)
    return {"ok": True, "settings": settings}


@app.post("/api/test")
async def api_test(request: Request) -> dict[str, Any]:
    streamer = await state.require_streamer(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    settings = await state.store.settings(streamer.broadcaster_id)
    event = await state.render_and_publish(
        streamer=streamer,
        event_id=uuid.uuid4().hex,
        user=str(payload.get("user") or "test viewer"),
        amount=max(1, int(payload.get("amount") or settings["minBits"] or 100)),
        message=str(payload.get("message") or "this is a test bit message"),
        settings=settings,
    )
    return {"ok": True, "event": event}


@app.post("/api/regenerate-overlay")
async def api_regenerate_overlay(request: Request) -> dict[str, str]:
    streamer = await state.require_streamer(request)
    streamer = await state.store.regenerate_overlay_key(streamer.broadcaster_id)
    return {"overlayUrl": f"{state.base_url(request)}/overlay/{streamer.overlay_key}"}


@app.post("/api/logout")
async def logout() -> Response:
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/overlay/{overlay_key}/events")
async def overlay_events(overlay_key: str) -> StreamingResponse:
    if not KEY_RE.fullmatch(overlay_key):
        raise HTTPException(status_code=404, detail="Overlay not found")
    streamer = await state.store.get_by_overlay_key(overlay_key)
    if streamer is None:
        raise HTTPException(status_code=404, detail="Overlay not found")
    queue = await state.hub.subscribe(overlay_key)

    async def generate() -> Any:
        try:
            yield sse("ready", {"ok": True, "streamer": streamer.display_name})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield sse("speech", event)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await state.hub.unsubscribe(overlay_key, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/audio/{audio_id}.wav")
async def audio(audio_id: str) -> FileResponse:
    if not AUDIO_ID_RE.fullmatch(audio_id):
        raise HTTPException(status_code=404, detail="Audio not found")
    path = state.audio_dir / f"{audio_id}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/wav", filename="ttsmodachi-stream.wav")


async def read_json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Invalid JSON") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    return payload


def require_stream_elements_secret(request: Request, payload: dict[str, Any]) -> None:
    if not state.se_secret:
        return
    supplied = (
        request.headers.get("x-alert-token")
        or request.query_params.get("token")
        or str(payload.get("token") or "")
    )
    if not hmac.compare_digest(supplied, state.se_secret):
        raise HTTPException(status_code=401, detail="Alert token required")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "configured": state.twitch.configured(),
        "streamers": len(await state.store.list_streamers()),
        "overlays": await state.hub.counts(),
    }


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def main() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    host = env_value("TTSMODACHI_STREAM_BIND", "0.0.0.0") or "0.0.0.0"
    port = env_int("TTSMODACHI_STREAM_PORT", 8082)
    uvicorn.run("ttsmodachi_bot.stream_service:app", host=host, port=port)


if __name__ == "__main__":
    main()

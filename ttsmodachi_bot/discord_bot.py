from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import socket
import tempfile
import time
import urllib.parse
from dataclasses import replace

import aiohttp
from pathlib import Path

import discord
from discord import app_commands

from .message_cleaner import clean_message
from .panel_tokens import create_panel_token
from .render_client import RendererClient
from .storage import Storage
from .voices import BUILTIN_VOICES, LANG_TO_ROM, VoiceParams
from .env import env_float, env_int, env_value


LOGGER = logging.getLogger(__name__)
VOICE_RECOVERY_MESSAGE = "Voice connection got stuck; reconnecting now."
VOICE_RECOVERY_NOTICE_SECONDS = 60.0
VOICE_CONNECT_TIMEOUT_SECONDS = 30.0
VOICE_WATCHDOG_SECONDS = 20.0
VOICE_MAX_CONSECUTIVE_RECOVERY_FAILURES = env_int("TTSMODACHI_VOICE_MAX_RECOVERY_FAILURES", 2)
VOICE_RECOVERY_GIVE_UP_MESSAGE = (
    "I couldn't reconnect to voice after repeated Discord timeouts. Run /join again if you still want TTS here."
)
VOICE_IDLE_DISCONNECT_SECONDS = env_float("TTSMODACHI_VOICE_IDLE_DISCONNECT_SECONDS", 300.0)
VOICE_ALONE_DISCONNECT_SECONDS = env_float("TTSMODACHI_VOICE_ALONE_DISCONNECT_SECONDS", 60.0)
VOICE_SELF_DEAF = (os.environ.get("TTSMODACHI_VOICE_SELF_DEAF") or "").lower() in {"1", "true", "yes", "on"}
VOICE_STARTUP_EMPTY_GRACE_SECONDS = env_float(
    "TTSMODACHI_VOICE_STARTUP_EMPTY_GRACE_SECONDS",
    max(90.0, VOICE_ALONE_DISCONNECT_SECONDS),
)
PLAYER_TASK_IDLE_EXIT_SECONDS = env_float("TTSMODACHI_PLAYER_TASK_IDLE_EXIT_SECONDS", 300.0)
USER_COOLDOWN_SECONDS = env_float("TTSMODACHI_USER_COOLDOWN_SECONDS", 0.5)
SECOND_BOT_INVITE_PERMISSIONS = env_int("TTSMODACHI_SECOND_BOT_INVITE_PERMISSIONS", 36785216)
SUPPORT_INVITE_URL = env_value("TTSMODACHI_SUPPORT_INVITE_URL")
MAINTENANCE_RESTART_MESSAGE = env_value(
    "TTSMODACHI_MAINTENANCE_RESTART_MESSAGE",
    "Bot is restarting for maintenance. I\'ll be back in a sec.",
)
MAINTENANCE_NOTICE_TIMEOUT_SECONDS = env_float("TTSMODACHI_MAINTENANCE_NOTICE_TIMEOUT_SECONDS", 20.0)
VOICE_CONNECT_EXCEPTIONS = (discord.ClientException, aiohttp.ClientError, asyncio.TimeoutError, TimeoutError)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_optional_int(name: str) -> int | None:
    value = env_value(name)
    return int(value) if value else None


def env_int_list(name: str) -> list[int] | None:
    value = env_value(name)
    if not value:
        return None
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def format_bool(value: bool) -> str:
    return "on" if value else "off"


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value.lower() in {"none", "null", "off", "reset"}:
        return None
    return value


def normalize_prefix(value: str | None) -> str | None:
    value = normalize_optional_text(value)
    if value is None:
        return None
    if len(value) > 5 or value.count(" ") > 1:
        raise ValueError("Use 5 or fewer characters with at most one space.")
    return value


def normalize_voice_id(name: str) -> str:
    return "-".join(name.lower().split())[:32]


def second_bot_invite_url() -> str | None:
    configured_url = env_value("TTSMODACHI_SECOND_BOT_INVITE_URL")
    if configured_url:
        return configured_url
    client_id = env_value("TTSMODACHI_SECOND_BOT_CLIENT_ID")
    if not client_id:
        return None
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "permissions": str(SECOND_BOT_INVITE_PERMISSIONS),
            "scope": "bot applications.commands",
        }
    )




def configured_worker_roms() -> set[str]:
    return {
        rom.strip().upper()
        for rom in (env_value("TTSMODACHI_WORKER_ROMS", "US") or "US").split(",")
        if rom.strip()
    }


def supported_voice_languages() -> list[str]:
    roms = configured_worker_roms()
    languages = [lang for lang, rom in LANG_TO_ROM.items() if rom.upper() in roms]
    return languages or ["useng"]


def is_voice_language_available(voice: VoiceParams) -> bool:
    return voice.lang in supported_voice_languages()


def coerce_supported_voice_language(voice: VoiceParams) -> VoiceParams:
    if is_voice_language_available(voice):
        return voice
    return replace(voice, lang=supported_voice_languages()[0])


def unsupported_language_message(lang: str) -> str:
    languages = ", ".join(supported_voice_languages())
    return f"Language `{lang}` needs a ROM this bot does not have right now. Available: `{languages}`."

def bot_name_for_message(storage: Storage, message: discord.Message) -> str:
    assert message.guild is not None
    nickname = storage.get_nickname(message.guild.id, message.author.id)
    if nickname:
        return nickname
    return message.author.display_name


def panel_url_for(
    guild_id: int,
    user_id: int,
    display_name: str | None = None,
    avatar_url: str | None = None,
    issued_at_ms: int | None = None,
) -> str:
    base_url = (env_value("TTSMODACHI_PANEL_URL", "http://127.0.0.1:18080") or "").rstrip("/")
    # Discord button URLs are limited to 512 chars, so keep profile data in storage instead of the token.
    token = create_panel_token(
        guild_id=guild_id,
        user_id=user_id,
        issued_at_ms=issued_at_ms,
    )
    return f"{base_url}/?{urllib.parse.urlencode({'token': token})}"


async def send_voice_panel(interaction: discord.Interaction, storage: Storage) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("Use /voice in a server to open your voice dashboard.", ephemeral=True)
        return
    display_name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", "Discord user")
    avatar_url = str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None
    issued_at_ms = time.time_ns() // 1_000_000
    already_linked = storage.get_panel_account_linked_at_ms(interaction.user.id) is not None
    try:
        url = panel_url_for(
            interaction.guild.id,
            interaction.user.id,
            display_name=display_name,
            avatar_url=avatar_url,
            issued_at_ms=issued_at_ms,
        )
    except RuntimeError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    if not already_linked:
        storage.link_panel_account(
            interaction.user.id,
            linked_at_ms=issued_at_ms,
            display_name=display_name,
            avatar_url=avatar_url,
        )

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Open voice dashboard", url=url))
    message = (
        "Your Discord account is already linked. Open the voice dashboard."
        if already_linked
        else "Linked your Discord account. Open the voice dashboard to customize it."
    )
    await interaction.response.send_message(message, view=view, ephemeral=True)


class GuildPlayer:
    def __init__(self, bot: "TTSModachiBot", guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: asyncio.Queue[tuple[str, VoiceParams, discord.abc.Messageable | None]] = asyncio.Queue(maxsize=20)
        self.task: asyncio.Task[None] | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.target_voice_channel_id: int | None = None
        self.status_channel_id: int | None = None
        self._connect_lock = asyncio.Lock()
        self._last_recovery_notice_at = 0.0
        self._voice_recovery_failures = 0
        self._last_activity_at = time.monotonic()
        self._alone_since_at: float | None = None

    async def connect(
        self,
        channel: discord.VoiceChannel | discord.StageChannel,
        status_channel: discord.abc.Messageable | None = None,
    ) -> None:
        self._touch()
        self.target_voice_channel_id = channel.id
        if status_channel is not None:
            self.status_channel_id = getattr(status_channel, "id", None)
        async with self._connect_lock:
            try:
                await self._connect_once(channel)
            except VOICE_CONNECT_EXCEPTIONS as error:
                if not self._should_recover_connect_error(error):
                    raise
                LOGGER.warning(
                    "Discord voice connection got stuck; resetting and retrying guild=%s channel=%s error=%s",
                    self.guild_id,
                    channel.id,
                    type(error).__name__,
                )
                await self._announce_recovery(status_channel)
                await self._reset_voice_client()
                await asyncio.sleep(1.0)
                try:
                    await self._connect_once(channel)
                except VOICE_CONNECT_EXCEPTIONS as retry_error:
                    if self._should_recover_connect_error(retry_error):
                        LOGGER.warning(
                            "Discord voice connection retry failed guild=%s channel=%s error=%s",
                            self.guild_id,
                            channel.id,
                            type(retry_error).__name__,
                        )
                    raise
        self._voice_recovery_failures = 0
        self._persist_voice_target()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    async def disconnect(self, clear_queue: bool = False) -> None:
        if clear_queue:
            self.clear()
        self._clear_persisted_voice_target()
        self.target_voice_channel_id = None
        self.status_channel_id = None
        self._voice_recovery_failures = 0
        await self._reset_voice_client()

    def forget_voice_target(self, clear_queue: bool = False, clear_persisted: bool = True) -> None:
        if clear_queue:
            self.clear()
        if clear_persisted:
            self._clear_persisted_voice_target()
        self.target_voice_channel_id = None
        self.status_channel_id = None
        self._voice_recovery_failures = 0
        self.voice_client = None

    def remember_voice_target(
        self,
        channel: discord.VoiceChannel | discord.StageChannel,
        status_channel: discord.abc.Messageable | None = None,
    ) -> None:
        self.target_voice_channel_id = channel.id
        if status_channel is not None:
            self.status_channel_id = getattr(status_channel, "id", None)
        self._persist_voice_target()

    def _persist_voice_target(self) -> None:
        if self.target_voice_channel_id is None or self.bot.user is None:
            return
        self.bot.storage.set_active_voice_target(
            bot_user_id=self.bot.user.id,
            guild_id=self.guild_id,
            voice_channel_id=self.target_voice_channel_id,
            status_channel_id=self.status_channel_id,
        )

    def _clear_persisted_voice_target(self) -> None:
        if self.bot.user is None:
            return
        self.bot.storage.clear_active_voice_target(bot_user_id=self.bot.user.id, guild_id=self.guild_id)

    async def announce_maintenance(self, message: str, audio: bytes | None) -> None:
        voice_client = self._current_voice_client()
        if voice_client is None or not voice_client.is_connected():
            return

        channel = getattr(voice_client, "channel", None)
        send = getattr(channel, "send", None)
        if callable(send):
            try:
                await send(message)
            except discord.Forbidden:
                LOGGER.info(
                    "Could not send maintenance notice in voice chat guild=%s channel=%s",
                    self.guild_id,
                    getattr(channel, "id", None),
                )
            except discord.HTTPException:
                LOGGER.debug("Could not send maintenance notice in voice chat", exc_info=True)

        if audio is None or not voice_client.is_connected():
            return
        self.clear()
        await asyncio.sleep(0.15)
        await self._play_audio_bytes(audio)

    async def ensure_voice_alive(self) -> None:
        if self.target_voice_channel_id is None:
            return
        if self.voice_client is not None and self.voice_client.is_connected():
            return
        channel = self._target_voice_channel()
        if channel is None:
            return
        status_channel = self._status_channel()
        await self._announce_recovery(status_channel)
        await self.connect(channel, status_channel)

    async def maintain_voice(self) -> None:
        if await self._disconnect_if_idle():
            return
        await self.ensure_voice_alive()

    async def enqueue(self, text: str, voice: VoiceParams, reply_to: discord.abc.Messageable | None = None) -> bool:
        try:
            self.queue.put_nowait((text, voice, reply_to))
        except asyncio.QueueFull:
            return False
        self._touch()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())
        return True

    def clear(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        self._touch()

    async def _run(self) -> None:
        while True:
            try:
                text, voice, reply_to = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=PLAYER_TASK_IDLE_EXIT_SECONDS,
                )
            except asyncio.TimeoutError:
                if self._is_discardable():
                    return
                continue
            try:
                self._touch()
                voice_client = self._current_voice_client()
                if voice_client is None or not voice_client.is_connected():
                    channel = self._target_voice_channel()
                    if channel is None:
                        continue
                    await self.connect(channel, reply_to)
                async with self.bot.render_slots:
                    self.bot.storage.increment_counter("tts_messages_submitted")
                    audio = await self.bot.renderer.render(text, voice)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
                    file.write(audio)
                    path = Path(file.name)
                voice_client = self._current_voice_client()
                if voice_client is None or not voice_client.is_connected():
                    channel = self._target_voice_channel()
                    if channel is None:
                        LOGGER.info("Dropping TTS playback because voice target disappeared before playback guild=%s", self.guild_id)
                        path.unlink(missing_ok=True)
                        continue
                    await self.connect(channel, reply_to)
                await self._play_file(path)
                self._touch()
            except Exception as error:
                LOGGER.exception("TTS playback job failed")
                if reply_to is not None:
                    try:
                        await reply_to.send(
                            "TTS failed for that message. The renderer is recovering, try again in a sec.",
                            delete_after=10,
                        )
                    except discord.Forbidden:
                        LOGGER.info("Could not send TTS failure notice because Discord denied channel access")
                    except discord.HTTPException:
                        LOGGER.debug("Could not send TTS failure notice", exc_info=True)
            finally:
                self.queue.task_done()

    async def _play_audio_bytes(self, audio: bytes) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
            file.write(audio)
            path = Path(file.name)
        await self._play_file(path)

    async def _play_file(self, path: Path) -> None:
        done = asyncio.Event()

        def after(error: Exception | None) -> None:
            if error:
                LOGGER.warning("Discord playback failed", exc_info=error)
            self.bot.loop.call_soon_threadsafe(done.set)

        source = discord.FFmpegPCMAudio(str(path))
        started = False
        try:
            voice_client = self._current_voice_client()
            if voice_client is None or not voice_client.is_connected():
                LOGGER.info("Dropping TTS playback because voice client disconnected before playback guild=%s", self.guild_id)
                return
            for _ in range(20):
                if not voice_client.is_playing():
                    break
                await asyncio.sleep(0.1)
            if voice_client.is_playing():
                LOGGER.info("Dropping TTS playback because voice client is still busy guild=%s", self.guild_id)
                return
            voice_client.play(source, after=after)
            started = True
            await done.wait()
        finally:
            if not started:
                source.cleanup()
            path.unlink(missing_ok=True)

    def _touch(self) -> None:
        self._last_activity_at = time.monotonic()
        self._alone_since_at = None

    def _is_discardable(self) -> bool:
        connected = self.voice_client is not None and self.voice_client.is_connected()
        return self.target_voice_channel_id is None and not connected and self.queue.empty()

    async def _disconnect_if_idle(self) -> bool:
        voice_client = self._current_voice_client()
        if voice_client is None or not voice_client.is_connected():
            return False
        if voice_client.is_playing() or not self.queue.empty():
            self._touch()
            return False

        now = time.monotonic()
        channel = getattr(voice_client, "channel", None)
        has_human_listener = channel is not None and self._has_human_listener(channel)
        if channel is not None and not has_human_listener:
            if self.bot._voice_empty_grace_active():
                if self._alone_since_at is None:
                    self._alone_since_at = now
                return False
            if self._alone_since_at is None:
                self._alone_since_at = now
            elif VOICE_ALONE_DISCONNECT_SECONDS > 0 and now - self._alone_since_at >= VOICE_ALONE_DISCONNECT_SECONDS:
                LOGGER.info("Leaving idle voice channel in guild %s because no listeners remain", self.guild_id)
                await self.disconnect(clear_queue=True)
                return True
        else:
            self._alone_since_at = None

        if (
            VOICE_IDLE_DISCONNECT_SECONDS > 0
            and not has_human_listener
            and now - self._last_activity_at >= VOICE_IDLE_DISCONNECT_SECONDS
        ):
            LOGGER.info("Leaving idle voice channel in guild %s after %.0f seconds", self.guild_id, VOICE_IDLE_DISCONNECT_SECONDS)
            await self.disconnect()
            return True
        return False

    def _has_human_listener(self, channel: object) -> bool:
        bot_user_id = self.bot.user.id if self.bot.user else None
        members = getattr(channel, "members", ())
        return any(
            getattr(member, "id", None) != bot_user_id and not getattr(member, "bot", False)
            for member in members
        )

    async def _connect_once(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        existing = self._current_voice_client()
        if existing is not None:
            self.voice_client = existing
            if existing.is_connected():
                if existing.channel != channel:
                    await existing.move_to(channel)
                return
            await self._drop_voice_client(existing)

        self.voice_client = await channel.connect(
            timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
            reconnect=True,
            self_deaf=VOICE_SELF_DEAF,
        )

    def _current_voice_client(self) -> discord.VoiceClient | None:
        if self.voice_client is not None:
            return self.voice_client
        for voice_client in self.bot.voice_clients:
            guild = getattr(voice_client, "guild", None)
            if getattr(guild, "id", None) == self.guild_id:
                return voice_client
        return None

    async def _reset_voice_client(self) -> None:
        voice_client = self._current_voice_client()
        if voice_client is not None:
            await self._drop_voice_client(voice_client)
        self.voice_client = None

    async def _drop_voice_client(self, voice_client: discord.VoiceClient) -> None:
        try:
            if voice_client.is_playing():
                voice_client.stop()
        except Exception:
            LOGGER.debug("Failed to stop Discord voice playback during recovery", exc_info=True)
        try:
            await voice_client.disconnect(force=True)
        except Exception:
            LOGGER.debug("Failed to disconnect Discord voice client during recovery", exc_info=True)
        cleanup = getattr(voice_client, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                LOGGER.debug("Failed to clean up Discord voice client during recovery", exc_info=True)
        if self.voice_client is voice_client:
            self.voice_client = None

    def _should_recover_connect_error(self, error: BaseException) -> bool:
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True
        if isinstance(error, discord.ClientException) and "Already connected" in str(error):
            return True
        if isinstance(error, aiohttp.ClientResponseError):
            return 500 <= error.status < 600
        return isinstance(error, aiohttp.ClientConnectionError)

    async def _announce_recovery(self, channel: discord.abc.Messageable | None) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_recovery_notice_at < VOICE_RECOVERY_NOTICE_SECONDS:
            return
        self._last_recovery_notice_at = now
        target = channel or self._status_channel()
        if target is None:
            return
        try:
            await target.send(VOICE_RECOVERY_MESSAGE)
        except discord.Forbidden:
            LOGGER.info("Could not send Discord voice recovery notice because Discord denied channel access")
        except discord.HTTPException:
            LOGGER.debug("Failed to send Discord voice recovery notice", exc_info=True)
        except Exception:
            LOGGER.debug("Failed to send Discord voice recovery notice", exc_info=True)

    def _target_voice_channel(self) -> discord.VoiceChannel | discord.StageChannel | None:
        if self.target_voice_channel_id is None:
            return None
        channel = self.bot.get_channel(self.target_voice_channel_id)
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(self.target_voice_channel_id)
        return channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None

    def _status_channel(self) -> discord.abc.Messageable | None:
        if self.status_channel_id is None:
            return None
        channel = self.bot.get_channel(self.status_channel_id)
        return channel if hasattr(channel, "send") else None


class TTSModachiBot(discord.AutoShardedClient):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True
        client_options: dict[str, object] = {
            "allowed_mentions": discord.AllowedMentions.none(),
            "intents": intents,
            "max_messages": env_int("TTSMODACHI_MAX_CACHED_MESSAGES", 100),
        }
        shard_count = env_optional_int("TTSMODACHI_SHARD_COUNT")
        shard_ids = env_int_list("TTSMODACHI_SHARD_IDS")
        if shard_count is not None:
            client_options["shard_count"] = shard_count
        if shard_ids is not None:
            client_options["shard_ids"] = shard_ids
        super().__init__(**client_options)
        self.tree = app_commands.CommandTree(self)
        self.storage = Storage(os.environ.get("DATABASE_PATH", "/data/ttsmodachi.sqlite3"))
        self.renderer = RendererClient(os.environ.get("RENDERER_URL", "http://tts-worker:8080"))
        self.players: dict[int, GuildPlayer] = {}
        self.render_slots = asyncio.Semaphore(env_int("TTSMODACHI_BOT_RENDER_CONCURRENCY", 16))
        self.user_cooldowns: dict[tuple[int, int], float] = {}
        self.sync_commands = env_bool("SYNC_COMMANDS_ON_START", True)
        self.runtime_instance_id = f"{socket.gethostname()}:{os.getpid()}"
        self.voice_watchdog_task: asyncio.Task[None] | None = None
        self.runtime_stats_task: asyncio.Task[None] | None = None
        self.restore_voice_targets_task: asyncio.Task[None] | None = None
        self._shutdown_notice_sent = False
        self._shutdown_in_progress = False
        self._voice_targets_restore_started = False
        self._voice_empty_grace_until = time.monotonic() + VOICE_STARTUP_EMPTY_GRACE_SECONDS

    async def setup_hook(self) -> None:
        register_commands(self)
        if self.sync_commands:
            await self.tree.sync()
        self.voice_watchdog_task = asyncio.create_task(self._voice_watchdog())
        self.runtime_stats_task = asyncio.create_task(self._runtime_stats_publisher())

    async def close(self) -> None:
        self._shutdown_in_progress = True
        self._persist_connected_voice_targets_for_restart()
        await self._announce_maintenance_shutdown()
        for task in (self.voice_watchdog_task, self.runtime_stats_task, self.restore_voice_targets_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.renderer.close()
        self.storage.close()
        await super().close()

    def _persist_connected_voice_targets_for_restart(self) -> None:
        if self.user is None:
            return
        persisted = 0
        for player in self.players.values():
            voice_client = player._current_voice_client()
            if voice_client is None or not voice_client.is_connected():
                continue
            channel = getattr(voice_client, "channel", None)
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                continue
            player.target_voice_channel_id = channel.id
            player._persist_voice_target()
            persisted += 1
        if persisted:
            LOGGER.info("Persisted %s active voice target(s) for restart", persisted)

    async def _announce_maintenance_shutdown(self) -> None:
        message = (MAINTENANCE_RESTART_MESSAGE or "").strip()
        if self._shutdown_notice_sent or not message:
            return
        self._shutdown_notice_sent = True
        players = [
            player
            for player in self.players.values()
            if (player._current_voice_client() is not None and player._current_voice_client().is_connected())
        ]
        if not players:
            return

        LOGGER.info("Announcing maintenance restart to %s active voice channel(s)", len(players))
        audio: bytes | None = None
        try:
            async with self.render_slots:
                audio = await self.renderer.render(message, BUILTIN_VOICES["adultf"])
        except Exception:
            LOGGER.warning("Failed to render maintenance voice notice; sending text only", exc_info=True)

        tasks = [asyncio.create_task(player.announce_maintenance(message, audio)) for player in players]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=MAINTENANCE_NOTICE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOGGER.warning(
                "Maintenance restart notice timed out after %.1f seconds",
                MAINTENANCE_NOTICE_TIMEOUT_SECONDS,
            )
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return

        for result in results:
            if isinstance(result, Exception):
                LOGGER.debug("Maintenance restart notice failed", exc_info=result)

    def player_for(self, guild_id: int) -> GuildPlayer:
        player = self.players.get(guild_id)
        if player is None:
            player = GuildPlayer(self, guild_id)
            self.players[guild_id] = player
        return player

    def _voice_empty_grace_active(self) -> bool:
        return time.monotonic() < self._voice_empty_grace_until

    async def on_ready(self) -> None:
        assert self.user is not None
        shard_count = getattr(self, "shard_count", None) or len(getattr(self, "shards", {})) or 1
        print(f"Logged in as {self.user} ({self.user.id}); guilds={len(self.guilds)} shards={shard_count}")
        await self._publish_runtime_stats()
        if not self._voice_targets_restore_started:
            self._voice_targets_restore_started = True
            self.restore_voice_targets_task = asyncio.create_task(self._restore_active_voice_targets())

    async def _restore_active_voice_targets(self) -> None:
        await asyncio.sleep(2.0)
        if self.user is None:
            return
        targets = self.storage.list_active_voice_targets(self.user.id)
        if not targets:
            return
        LOGGER.info("Restoring %s active voice target(s) after startup", len(targets))
        self._voice_empty_grace_until = max(
            self._voice_empty_grace_until,
            time.monotonic() + VOICE_STARTUP_EMPTY_GRACE_SECONDS,
        )
        semaphore = asyncio.Semaphore(env_int("TTSMODACHI_REJOIN_CONCURRENCY", 3))

        async def restore_target(target) -> None:
            async with semaphore:
                channel = self.get_channel(target.voice_channel_id)
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    LOGGER.info(
                        "Dropping stale voice target guild=%s channel=%s because the channel is unavailable",
                        target.guild_id,
                        target.voice_channel_id,
                    )
                    self.storage.clear_active_voice_target(bot_user_id=self.user.id, guild_id=target.guild_id)
                    return
                player = self.player_for(target.guild_id)
                status_channel = self.get_channel(target.status_channel_id) if target.status_channel_id else None
                if not isinstance(status_channel, discord.abc.Messageable):
                    status_channel = channel
                try:
                    await player.connect(channel, status_channel)
                    LOGGER.info("Restored voice target guild=%s channel=%s", target.guild_id, target.voice_channel_id)
                except discord.Forbidden:
                    LOGGER.info(
                        "Dropping active voice target guild=%s channel=%s because Discord denied voice access",
                        target.guild_id,
                        target.voice_channel_id,
                    )
                    await player.disconnect(clear_queue=True)
                except (discord.ClientException, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as error:
                    LOGGER.warning(
                        "Failed to restore voice target guild=%s channel=%s error=%s",
                        target.guild_id,
                        target.voice_channel_id,
                        type(error).__name__,
                    )

        await asyncio.gather(*(restore_target(target) for target in targets))
        await self._publish_runtime_stats()

    async def _runtime_stats_publisher(self) -> None:
        while not self.is_closed():
            try:
                await self._publish_runtime_stats()
            except Exception:
                LOGGER.debug("Failed to publish bot runtime stats", exc_info=True)
            await asyncio.sleep(15)

    async def _publish_runtime_stats(self) -> None:
        shard_count = getattr(self, "shard_count", None) or len(getattr(self, "shards", {})) or 1
        voice_connection_count = sum(
            1
            for voice_client in self.voice_clients
            if voice_client is not None and voice_client.is_connected()
        )
        user = self.user
        bot_user_id = user.id if user else None
        active_user_ids = {
            member_id
            for voice_client in self.voice_clients
            if voice_client is not None and voice_client.is_connected()
            for member in getattr(getattr(voice_client, "channel", None), "members", ())
            for member_id in (getattr(member, "id", None),)
            if member_id is not None and member_id != bot_user_id and not getattr(member, "bot", False)
        }
        active_player_count = sum(1 for player in self.players.values() if not player._is_discardable())
        queued_message_count = sum(player.queue.qsize() for player in self.players.values())
        self.storage.update_bot_runtime(
            instance_id=self.runtime_instance_id,
            bot_user_id=bot_user_id,
            bot_name=str(user) if user else None,
            guild_count=len(self.guilds),
            voice_connection_count=voice_connection_count,
            active_user_count=len(active_user_ids),
            active_player_count=active_player_count,
            queued_message_count=queued_message_count,
            shard_count=int(shard_count),
        )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if self.user is not None and member.id == self.user.id:
            player = self.players.get(member.guild.id)
            if player is not None and after.channel is None:
                player.forget_voice_target(clear_queue=True, clear_persisted=not self._shutdown_in_progress)
            elif player is not None and isinstance(after.channel, (discord.VoiceChannel, discord.StageChannel)):
                player.remember_voice_target(after.channel)
            return

        checked_channel_ids: set[int] = set()
        for channel in (before.channel, after.channel):
            if channel is None or channel.id in checked_channel_ids:
                continue
            checked_channel_ids.add(channel.id)
            await self._leave_if_empty_voice_channel(channel)

    async def _leave_if_empty_voice_channel(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        player = self.players.get(channel.guild.id)
        if player is None:
            return
        voice_client = player._current_voice_client()
        if voice_client is None or not voice_client.is_connected():
            return
        if getattr(getattr(voice_client, "channel", None), "id", None) != channel.id:
            return
        if player._has_human_listener(channel):
            return
        if self._voice_empty_grace_active():
            LOGGER.info(
                "Deferring empty voice cleanup during startup grace guild=%s channel=%s",
                channel.guild.id,
                channel.id,
            )
            return
        LOGGER.info("Leaving voice channel %s in guild %s because no listeners remain", channel.id, channel.guild.id)
        await player.disconnect(clear_queue=True)

    async def _voice_watchdog(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(VOICE_WATCHDOG_SECONDS)
            for player in list(self.players.values()):
                try:
                    await player.maintain_voice()
                    player._voice_recovery_failures = 0
                    if player._is_discardable() and (player.task is None or player.task.done()):
                        self.players.pop(player.guild_id, None)
                except (discord.ClientException, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as error:
                    if not player._should_recover_connect_error(error):
                        LOGGER.warning(
                            "Discord voice watchdog failed guild=%s error=%s",
                            player.guild_id,
                            type(error).__name__,
                        )
                        continue
                    player._voice_recovery_failures += 1
                    if player._voice_recovery_failures >= VOICE_MAX_CONSECUTIVE_RECOVERY_FAILURES:
                        LOGGER.warning(
                            "Dropping stale voice target guild=%s after %s reconnect failure(s) error=%s",
                            player.guild_id,
                            player._voice_recovery_failures,
                            type(error).__name__,
                        )
                        status_channel = player._status_channel()
                        if status_channel is not None:
                            try:
                                await status_channel.send(VOICE_RECOVERY_GIVE_UP_MESSAGE)
                            except discord.Forbidden:
                                LOGGER.info("Could not send Discord voice give-up notice because Discord denied channel access")
                            except discord.HTTPException:
                                LOGGER.debug("Could not send Discord voice give-up notice", exc_info=True)
                        await player.disconnect(clear_queue=True)
                    else:
                        LOGGER.warning(
                            "Discord voice watchdog reconnect failed guild=%s attempt=%s/%s error=%s",
                            player.guild_id,
                            player._voice_recovery_failures,
                            VOICE_MAX_CONSECUTIVE_RECOVERY_FAILURES,
                            type(error).__name__,
                        )
                except Exception:
                    LOGGER.exception("Discord voice watchdog recovery failed")

    def _is_user_rate_limited(self, guild_id: int, user_id: int) -> bool:
        if USER_COOLDOWN_SECONDS <= 0:
            return False
        now = time.monotonic()
        key = (guild_id, user_id)
        last_seen = self.user_cooldowns.get(key)
        if last_seen is not None and now - last_seen < USER_COOLDOWN_SECONDS:
            return True
        self.user_cooldowns[key] = now
        if len(self.user_cooldowns) > 10000:
            cutoff = now - max(60.0, USER_COOLDOWN_SECONDS * 4)
            self.user_cooldowns = {cooldown_key: ts for cooldown_key, ts in self.user_cooldowns.items() if ts >= cutoff}
        return False

    @staticmethod
    def _is_automated_message(message: discord.Message) -> bool:
        return bool(getattr(message.author, "bot", False) or message.webhook_id is not None)

    @staticmethod
    def _message_text_for_tts(message: discord.Message, *, include_embeds: bool) -> str:
        content = (message.content or "").strip()
        if content or not include_embeds:
            return content

        parts: list[str] = []
        for embed in getattr(message, "embeds", ())[:3]:
            for value in (embed.title, embed.description):
                if value:
                    parts.append(str(value))
            for field in getattr(embed, "fields", ())[:4]:
                for value in (field.name, field.value):
                    if value:
                        parts.append(str(value))
            footer_text = getattr(getattr(embed, "footer", None), "text", None)
            if footer_text:
                parts.append(str(footer_text))
        return "\n".join(part.strip() for part in parts if part and part.strip())

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return

        if self.user is not None and message.author.id == self.user.id:
            return

        settings = self.storage.get_guild_settings(message.guild.id)
        automated_message = self._is_automated_message(message)
        if settings.ignore_bots and automated_message:
            return

        author_vc = message.author.voice.channel if isinstance(message.author, discord.Member) and message.author.voice else None
        player = self.players.get(message.guild.id)
        voice_client = player._current_voice_client() if player is not None else None
        bot_vc = getattr(voice_client, "channel", None) if voice_client is not None and voice_client.is_connected() else None
        configured_text_channel = (
            settings.setup_channel_id is not None
            and getattr(message.channel, "id", None) == settings.setup_channel_id
        )
        voice_chat_channel = message.channel if isinstance(message.channel, (discord.VoiceChannel, discord.StageChannel)) else None
        target_voice_channel: discord.VoiceChannel | discord.StageChannel | None = None
        target_from_active_player = False
        if configured_text_channel:
            if isinstance(bot_vc, (discord.VoiceChannel, discord.StageChannel)):
                target_voice_channel = bot_vc
                target_from_active_player = True
            elif isinstance(author_vc, (discord.VoiceChannel, discord.StageChannel)):
                target_voice_channel = author_vc
        elif voice_chat_channel is None or not settings.text_in_voice:
            return
        else:
            author_in_this_vc = author_vc is not None and author_vc.id == voice_chat_channel.id
            bot_in_this_vc = bot_vc is not None and getattr(bot_vc, "id", None) == voice_chat_channel.id
            should_read_non_vc = settings.read_non_vc_messages and (
                author_vc is None or author_vc.id != voice_chat_channel.id
            )
            should_read_automated = automated_message and (settings.read_non_vc_messages or bot_in_this_vc)
            if not (author_in_this_vc or should_read_non_vc or should_read_automated):
                return
            target_voice_channel = voice_chat_channel
            target_from_active_player = bot_in_this_vc

        message_text = self._message_text_for_tts(message, include_embeds=automated_message)
        raw_content = (message.content or "").strip()
        if not automated_message and raw_content.lower() == "-skip":
            player = self.player_for(message.guild.id)
            voice_client = player._current_voice_client()
            can_skip = True
            if voice_client is not None and voice_client.is_connected():
                voice_channel_id = getattr(getattr(voice_client, "channel", None), "id", None)
                permissions = getattr(message.author, "guild_permissions", None)
                can_manage = bool(permissions and (permissions.manage_guild or permissions.administrator))
                can_skip = bool(can_manage or (author_vc is not None and voice_channel_id == author_vc.id))
            if can_skip:
                player.clear()
                await message.add_reaction("\N{THUMBS UP SIGN}")
            return

        if not automated_message and raw_content.startswith("-"):
            return
        if not automated_message and settings.required_prefix is None and message.content.startswith(("/", "!", ".")):
            return
        if settings.required_role_id and isinstance(message.author, discord.Member) and not automated_message:
            if settings.required_role_id not in {role.id for role in message.author.roles}:
                return

        if author_vc is None:
            if target_voice_channel is None:
                if not automated_message:
                    return
                if player is None:
                    return
                target_voice_channel = player._target_voice_channel()
                target_from_active_player = True
            if target_voice_channel is None:
                return

        player = player or self.player_for(message.guild.id)
        voice_client = player._current_voice_client()
        if target_voice_channel is None:
            return
        if voice_client is None or not voice_client.is_connected():
            if not settings.autojoin and not target_from_active_player:
                return
            try:
                await player.connect(target_voice_channel, message.channel)
            except discord.Forbidden:
                LOGGER.info(
                    "Autojoin failed because Discord denied voice access guild=%s channel=%s",
                    message.guild.id,
                    getattr(target_voice_channel, "id", None),
                )
                await player.disconnect(clear_queue=False)
                return
            except (discord.ClientException, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as error:
                LOGGER.warning(
                    "Autojoin failed guild=%s channel=%s error=%s",
                    message.guild.id,
                    getattr(target_voice_channel, "id", None),
                    type(error).__name__,
                )
                await player.disconnect(clear_queue=False)
                return
        else:
            voice_channel_id = getattr(getattr(voice_client, "channel", None), "id", None)
            if voice_channel_id != target_voice_channel.id and (voice_chat_channel is not None or settings.require_same_vc):
                return

        text = clean_message(
            message_text,
            attachments=[attachment.filename for attachment in message.attachments],
            skip_emoji=settings.skip_emoji,
            repeated_chars=settings.repeated_characters,
            required_prefix=None if automated_message else settings.required_prefix,
            announce_name=(
                bot_name_for_message(self.storage, message)
                if settings.announce_name
                else None
            ),
            replacements=self.storage.list_replacements(message.guild.id),
        )
        if not text:
            return
        text = text[: settings.max_message_length]
        if self._is_user_rate_limited(message.guild.id, message.author.id):
            return

        voice_id = (
            self.storage.get_global_user_default(message.author.id)
            or self.storage.get_user_default(message.guild.id, message.author.id)
            or settings.default_voice_id
        )
        voice = coerce_supported_voice_language(self.storage.resolve_voice(voice_id, message.guild.id, message.author.id))
        queued = await player.enqueue(text, voice, message.channel)
        if not queued:
            await message.add_reaction("⏳")


def register_commands(bot: TTSModachiBot) -> None:
    def has_manager_permissions(interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(permissions and (permissions.manage_guild or permissions.administrator))

    def format_permission_name(permission: str) -> str:
        names = {
            "administrator": "Administrator",
            "manage_guild": "Manage Server",
            "manage_nicknames": "Manage Nicknames",
        }
        return names.get(permission, permission.replace("_", " " ).title())

    async def send_permission_error(interaction: discord.Interaction, message: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            LOGGER.debug("Could not send app command permission error response", exc_info=True)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            permissions = ", ".join(format_permission_name(name) for name in error.missing_permissions)
            await send_permission_error(
                interaction,
                f"You need {permissions} to use this command.",
            )
            return

        if isinstance(error, app_commands.BotMissingPermissions):
            permissions = ", ".join(format_permission_name(name) for name in error.missing_permissions)
            await send_permission_error(
                interaction,
                f"I need {permissions} to do that.",
            )
            return

        if isinstance(error, app_commands.CheckFailure):
            await send_permission_error(interaction, "You do not have permission to use this command.")
            return

        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        LOGGER.error("Unhandled exception in app command %s", command_name, exc_info=error)

    def interaction_voice_channel(interaction: discord.Interaction) -> discord.VoiceChannel | discord.StageChannel | None:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None:
            return None
        channel = member.voice.channel
        return channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None

    def current_player_channel(player: GuildPlayer) -> discord.VoiceChannel | discord.StageChannel | None:
        voice_client = player._current_voice_client()
        if voice_client is None or not voice_client.is_connected():
            return None
        channel = getattr(voice_client, "channel", None)
        return channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None

    def can_control_player(interaction: discord.Interaction, player: GuildPlayer) -> bool:
        if has_manager_permissions(interaction):
            return True
        channel = current_player_channel(player)
        if channel is None:
            return True
        user_channel = interaction_voice_channel(interaction)
        return user_channel is not None and user_channel.id == channel.id

    def can_move_player_to(interaction: discord.Interaction, player: GuildPlayer, target_channel: discord.VoiceChannel | discord.StageChannel) -> bool:
        if has_manager_permissions(interaction):
            return True
        channel = current_player_channel(player)
        if channel is None or channel.id == target_channel.id:
            return True
        return not player._has_human_listener(channel)

    def player_is_busy_elsewhere(player: GuildPlayer, target_channel: discord.VoiceChannel | discord.StageChannel) -> bool:
        channel = current_player_channel(player)
        return channel is not None and channel.id != target_channel.id and player._has_human_listener(channel)

    async def send_second_bot_invite(interaction: discord.Interaction) -> None:
        invite_url = second_bot_invite_url()
        view = discord.ui.View() if invite_url else None
        if view is not None and invite_url:
            view.add_item(discord.ui.Button(label="Invite TTSModachi 2", url=invite_url))
        await interaction.response.send_message(
            "I\x27m already in another vc! please disconnect me, or invite the second bot here:",
            view=view,
            ephemeral=True,
        )

    async def reject_player_control(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Join the bot's current voice channel, or ask someone with Manage Server to do that.",
            ephemeral=True,
        )

    async def send_commands_help(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="TTSModachi commands",
            description="Most replies are private to you. Commands marked Manage Server need server permissions.",
        )
        embed.add_field(
            name="Basics",
            value="\n".join(
                [
                    "`/help` or `/commands` - Show this command list.",
                    "`/settings` - Show this server's TTS settings.",
                    "`/join` - Join your current voice channel.",
                    "`/leave` - Leave the current voice channel.",
                    "`/channel` - Set the text channel to read into the current voice channel. Manage Server.",
                    "`/skip` - Stop current playback and clear the queue.",
                    "`-skip` - Text shortcut for skip; reacts with a thumbs up.",
                    "`-message` - Keep that message from being read aloud.",
                    "`/voice` - Link your Discord account or open your voice dashboard.",
                    "`/support` - Get the support Discord invite.",
                    "`/unlink` - Unlink your Discord account from the voice dashboard.",
                ]
            ),
            inline=False,
        )
        embed.add_field(
            name="Your voice",
            value="\n".join(
                [
                    "`/voices current` - Show your selected voice.",
                    "`/voices list` - List built-in and saved voices you can use.",
                    "`/voices use` - Select a voice by ID.",
                    "`/voices random` - Pick a random built-in voice.",
                    "`/voices save` - Save/select a custom voice from command options.",
                    "`/voices delete` - Delete one of your saved custom voices.",
                ]
            ),
            inline=False,
        )
        embed.add_field(
            name="Server settings",
            value="\n".join(
                [
                    "`/set autojoin` - Let the bot autojoin when TTS is sent. Manage Server.",
                    "`/set require_same_vc` - Only read users in the bot's VC. Manage Server.",
                    "`/set text_in_voice` - Read Discord text-in-voice channels. Manage Server.",
                    "`/set read_non_vc_messages` - Read VC chat from people not in VC. Manage Server.",
                    "`/set required_prefix` - Require a prefix before TTS. Manage Server.",
                    "`/set required_role` - Require a role to use TTS. Manage Server.",
                    "`/set message_length` - Cap message length. Manage Server.",
                ]
            ),
            inline=False,
        )
        embed.add_field(
            name="More settings",
            value="\n".join(
                [
                    "`/set repeated_characters` - Clamp repeated letters. Manage Server.",
                    "`/set say_name` - Toggle '<name> said'. Manage Server.",
                    "`/set nickname` - Set a TTS display name. Manage Server.",
                    "`/set say_emoji` - Read emoji names. Manage Server.",
                    "`/set skip_emoji` - Skip emoji. Manage Server.",
                    "`/set bot_ignore` - Ignore bots/webhooks. Manage Server.",
                    "`/set server_voice` - Set server default voice. Manage Server.",
                ]
            ),
            inline=False,
        )
        embed.add_field(
            name="Pronunciation",
            value="\n".join(
                [
                    "`/replace list` - Show pronunciation replacements. Manage Server.",
                    "`/replace add` - Add a word/phrase replacement. Manage Server.",
                    "`/replace remove` - Remove one replacement. Manage Server.",
                    "`/replace clear` - Remove all replacements. Manage Server.",
                ]
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="help", description="Show TTSModachi commands.")
    async def help_command(interaction: discord.Interaction) -> None:
        await send_commands_help(interaction)

    @bot.tree.command(name="commands", description="Show TTSModachi commands.")
    async def commands(interaction: discord.Interaction) -> None:
        await send_commands_help(interaction)

    @bot.tree.command(name="support", description="Get the support Discord invite.")
    async def support(interaction: discord.Interaction) -> None:
        if not SUPPORT_INVITE_URL:
            await interaction.response.send_message("support is in the discord!", ephemeral=True)
            return

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join Discord", url=SUPPORT_INVITE_URL))
        await interaction.response.send_message("support is in the discord!", view=view, ephemeral=True)

    @bot.tree.command(name="unlink", description="Unlink your Discord account from the voice dashboard.")
    async def unlink(interaction: discord.Interaction) -> None:
        removed_link = bot.storage.unlink_panel_account(interaction.user.id)
        removed_voice = bot.storage.delete_voice(voice_id="panel", guild_id=None, owner_user_id=interaction.user.id)
        bot.storage.set_global_user_default(interaction.user.id, None)
        if removed_link or removed_voice:
            await interaction.response.send_message("Unlinked your Discord account from the voice dashboard.", ephemeral=True)
        else:
            await interaction.response.send_message("Your account was not linked to the voice dashboard.", ephemeral=True)

    @bot.tree.command(name="join", description="Join your voice channel.")
    async def join(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return
        voice_channel = member.voice.channel
        player = bot.player_for(interaction.guild.id)
        if player_is_busy_elsewhere(player, voice_channel):
            await send_second_bot_invite(interaction)
            return
        if not can_move_player_to(interaction, player, voice_channel):
            await reject_player_control(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.connect(voice_channel, interaction.channel)
        except discord.Forbidden:
            await player.disconnect(clear_queue=False)
            await interaction.followup.send(
                "I don't have permission to join or speak in that voice channel.",
                ephemeral=True,
            )
            return
        except (discord.ClientException, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as error:
            LOGGER.warning(
                "Join command failed guild=%s channel=%s error=%s",
                interaction.guild.id,
                getattr(voice_channel, "id", None),
                type(error).__name__,
            )
            await player.disconnect(clear_queue=False)
            await interaction.followup.send(
                "Discord voice got stuck while I was joining. Try `/join` again in a sec.",
                ephemeral=True,
            )
            return
        await interaction.followup.send("Joined. Type in this voice channel's chat.", ephemeral=True)

    @bot.tree.command(name="leave", description="Leave the current voice channel.")
    async def leave(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = bot.player_for(interaction.guild.id)
        if not can_control_player(interaction, player):
            await reject_player_control(interaction)
            return
        await player.disconnect()
        await interaction.response.send_message("Left voice channel.", ephemeral=True)

    @bot.tree.command(name="skip", description="Clear queued TTS and stop current playback.")
    async def skip(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = bot.player_for(interaction.guild.id)
        if not can_control_player(interaction, player):
            await reject_player_control(interaction)
            return
        player.clear()
        await interaction.response.send_message("Cleared the queue.", ephemeral=True)

    @bot.tree.command(name="settings", description="Show TTSModachi settings for this server.")
    async def settings(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        row = bot.storage.get_guild_settings(interaction.guild.id)
        configured_channel = f"<#{row.setup_channel_id}>" if row.setup_channel_id else "none"
        required_role = f"<@&{row.required_role_id}>" if row.required_role_id else "none"
        required_prefix = row.required_prefix if row.required_prefix else "none"
        replacements = len(bot.storage.list_replacements(interaction.guild.id))
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Autojoin: {format_bool(row.autojoin)}",
                    f"Require same VC: {format_bool(row.require_same_vc)}",
                    f"Ignore bots: {format_bool(row.ignore_bots)}",
                    f"Text channel: {configured_channel}",
                    f"Text-in-voice: {format_bool(row.text_in_voice)}",
                    f"Read non-VC voice chat: {format_bool(row.read_non_vc_messages)}",
                    f"Say names: {format_bool(row.announce_name)}",
                    f"Say emoji: {format_bool(not row.skip_emoji)}",
                    f"Required prefix: {required_prefix}",
                    f"Required role: {required_role}",
                    f"Default voice: {row.default_voice_id}",
                    f"Max message length: {row.max_message_length}",
                    f"Repeated character limit: {row.repeated_characters}",
                    f"Replacements: {replacements}",
                ]
            ),
            ephemeral=True,
        )

    @bot.tree.command(name="channel", description="Set the text channel TTSmodachi reads from.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        assert interaction.guild is not None
        if channel is not None:
            permissions = channel.permissions_for(interaction.guild.me) if interaction.guild.me else None
            if permissions is not None and not permissions.view_channel:
                await interaction.response.send_message(
                    f"I cannot see {channel.mention}. Give me View Channel there first.",
                    ephemeral=True,
                )
                return
            bot.storage.set_guild_value(interaction.guild.id, "setup_channel_id", channel.id)
            await interaction.response.send_message(
                f"I'll read messages from {channel.mention} into the voice channel I'm joined in.",
                ephemeral=True,
            )
            return

        bot.storage.set_guild_value(interaction.guild.id, "setup_channel_id", None)
        await interaction.response.send_message(
            "Cleared the text channel. I'll only use voice channel chat unless you set `/channel` again.",
            ephemeral=True,
        )

    set_group = app_commands.Group(
        name="set",
        description="Change TTSModachi settings.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def set_bool(interaction: discord.Interaction, column: str, label: str, value: bool) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, column, int(value))
        await interaction.response.send_message(f"{label} is now {format_bool(value)}.", ephemeral=True)

    @set_group.command(name="autojoin", description="Allow automatic voice join when someone sends TTS.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_autojoin(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "autojoin", "Autojoin", enabled)

    @set_group.command(name="say_name", description="Say '<name> said' before each message.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_say_name(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "announce_name", "Saying names", enabled)

    @set_group.command(name="say_emoji", description="Say emoji names instead of skipping emoji.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_say_emoji(interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "skip_emoji", int(not enabled))
        await interaction.response.send_message(f"Saying emoji is now {format_bool(enabled)}.", ephemeral=True)

    @set_group.command(name="skip_emoji", description="Skip emoji within messages.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_skip_emoji(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "skip_emoji", "Skipping emoji", enabled)

    @set_group.command(name="bot_ignore", description="Ignore messages from bots and webhooks.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_bot_ignore(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "ignore_bots", "Bot ignore", enabled)

    @set_group.command(name="require_same_vc", description="Only read users in the same voice channel as the bot.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_require_same_vc(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "require_same_vc", "Require same VC", enabled)

    @set_group.command(name="text_in_voice", description="Read Discord text-in-voice channels.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_text_in_voice(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "text_in_voice", "Text-in-voice", enabled)

    @set_group.command(name="read_non_vc_messages", description="Read VC chat from people not in that voice channel.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_read_non_vc_messages(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "read_non_vc_messages", "Read non-VC voice chat", enabled)

    @set_group.command(name="required_prefix", description="Require a prefix before TTS messages.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_required_prefix(interaction: discord.Interaction, prefix: str | None = None) -> None:
        assert interaction.guild is not None
        try:
            normalized = normalize_prefix(prefix)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        bot.storage.set_guild_value(interaction.guild.id, "required_prefix", normalized)
        rendered = normalized if normalized else "none"
        await interaction.response.send_message(f"Required prefix is now `{rendered}`.", ephemeral=True)

    @set_group.command(name="required_role", description="Require a Discord role to use TTS.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_required_role(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "required_role_id", role.id if role else None)
        rendered = role.mention if role else "none"
        await interaction.response.send_message(f"Required role is now {rendered}.", ephemeral=True)

    @set_group.command(name="message_length", description="Set the maximum TTS message length.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_message_length(interaction: discord.Interaction, length: app_commands.Range[int, 20, 500]) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "max_message_length", int(length))
        await interaction.response.send_message(f"Max message length is now {length}.", ephemeral=True)

    @set_group.command(name="repeated_characters", description="Clamp long repeated character runs.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_repeated_characters(interaction: discord.Interaction, limit: app_commands.Range[int, 0, 20]) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "repeated_characters", int(limit))
        rendered = "off" if limit == 0 else str(limit)
        await interaction.response.send_message(f"Repeated character clamp is now {rendered}.", ephemeral=True)

    @set_group.command(name="nickname", description="Change the name used in '<name> said'.")
    async def set_nickname(
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        nickname: str | None = None,
    ) -> None:
        assert interaction.guild is not None
        target = user or interaction.user
        assert isinstance(target, (discord.Member, discord.User))
        if target.id != interaction.user.id:
            permissions = getattr(interaction.user, "guild_permissions", None)
            if permissions is None or not permissions.manage_nicknames:
                await interaction.response.send_message("You need Manage Nicknames to change someone else's TTS name.", ephemeral=True)
                return
        normalized = normalize_optional_text(nickname)
        if normalized and (len(normalized) > 100 or ("<" in normalized and ">" in normalized)):
            await interaction.response.send_message("Use 100 or fewer characters and no mentions/custom emoji.", ephemeral=True)
            return
        bot.storage.set_nickname(interaction.guild.id, target.id, normalized)
        if normalized:
            await interaction.response.send_message(f"TTS name for {target.mention} is now `{normalized}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Reset TTS name for {target.mention}.", ephemeral=True)

    @set_group.command(name="server_voice", description="Set the server default voice.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_server_voice(interaction: discord.Interaction, voice_id: str) -> None:
        assert interaction.guild is not None
        if not bot.storage.has_voice(voice_id, interaction.guild.id, None):
            await interaction.response.send_message("No matching server voice found. Use a built-in voice for server defaults.", ephemeral=True)
            return
        bot.storage.set_guild_value(interaction.guild.id, "default_voice_id", voice_id)
        await interaction.response.send_message(f"Server default voice is now `{voice_id}`.", ephemeral=True)

    bot.tree.add_command(set_group)

    replace_group = app_commands.Group(
        name="replace",
        description="Manage TTS pronunciation replacements.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @replace_group.command(name="add", description="Replace one word or phrase with another before TTS.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def replacement_add(interaction: discord.Interaction, source: str, replacement: str) -> None:
        assert interaction.guild is not None
        source = source.strip().lower()
        replacement = replacement.strip()
        if not source or not replacement or len(source) > 80 or len(replacement) > 120:
            await interaction.response.send_message("Use a source under 80 chars and replacement under 120 chars.", ephemeral=True)
            return
        bot.storage.set_replacement(interaction.guild.id, source, replacement)
        await interaction.response.send_message(f"`{source}` will be read as `{replacement}`.", ephemeral=True)

    @replace_group.command(name="remove", description="Remove a pronunciation replacement.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def replacement_remove(interaction: discord.Interaction, source: str) -> None:
        assert interaction.guild is not None
        deleted = bot.storage.delete_replacement(interaction.guild.id, source.strip().lower())
        await interaction.response.send_message("Removed." if deleted else "No matching replacement found.", ephemeral=True)

    @replace_group.command(name="clear", description="Remove all pronunciation replacements.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def replacement_clear(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        count = bot.storage.clear_replacements(interaction.guild.id)
        await interaction.response.send_message(f"Removed {count} replacements.", ephemeral=True)

    @replace_group.command(name="list", description="List pronunciation replacements.")
    async def replacement_list(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        replacements = bot.storage.list_replacements(interaction.guild.id)
        if not replacements:
            await interaction.response.send_message("No replacements configured.", ephemeral=True)
            return
        rendered = "\n".join(f"`{source}` -> `{replacement}`" for source, replacement in replacements[:25])
        await interaction.response.send_message(rendered, ephemeral=True)

    bot.tree.add_command(replace_group)

    @bot.tree.command(name="voice", description="customize your TTSmodachi voice!")
    async def voice(interaction: discord.Interaction) -> None:
        await send_voice_panel(interaction, bot.storage)

    voice_group = app_commands.Group(name="voices", description="Manual TTSModachi voice controls.")

    @voice_group.command(name="list", description="List available voices.")
    async def voice_list(interaction: discord.Interaction) -> None:
        guild_id = interaction.guild.id if interaction.guild is not None else 0
        voices = bot.storage.list_voices(guild_id, interaction.user.id)
        rendered = ", ".join(f"`{voice_id}`" for voice_id, _ in voices[:40])
        await interaction.response.send_message(rendered or "No voices available.", ephemeral=True)

    @voice_group.command(name="use", description="Use a voice for your messages.")
    async def voice_use(interaction: discord.Interaction, voice_id: str) -> None:
        guild_id = interaction.guild.id if interaction.guild is not None else None
        if not bot.storage.has_voice(voice_id, guild_id, interaction.user.id):
            await interaction.response.send_message("No matching voice found.", ephemeral=True)
            return
        bot.storage.set_global_user_default(interaction.user.id, voice_id)
        await interaction.response.send_message(f"Your voice is now `{voice_id}`.", ephemeral=True)

    @voice_group.command(name="current", description="Show your current voice.")
    async def voice_current(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            voice_id = bot.storage.get_global_user_default(interaction.user.id)
            if voice_id:
                await interaction.response.send_message(f"Your voice is `{voice_id}`.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "Using the built-in `adultf` voice. Use `/voices random` or `/voices use` to pick one.",
                    ephemeral=True,
                )
            return
        settings = bot.storage.get_guild_settings(interaction.guild.id)
        voice_id = bot.storage.get_global_user_default(interaction.user.id) or bot.storage.get_user_default(
            interaction.guild.id,
            interaction.user.id,
        )
        if voice_id:
            await interaction.response.send_message(f"Your voice is `{voice_id}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Using server default `{settings.default_voice_id}`.", ephemeral=True)

    @voice_group.command(name="random", description="Use a random built-in voice.")
    async def voice_random(interaction: discord.Interaction) -> None:
        voice_id = random.choice(list(BUILTIN_VOICES))
        bot.storage.set_global_user_default(interaction.user.id, voice_id)
        await interaction.response.send_message(f"Your voice is now `{voice_id}`.", ephemeral=True)

    @voice_group.command(name="save", description="Save a custom voice.")
    async def voice_save(
        interaction: discord.Interaction,
        name: str,
        pitch: app_commands.Range[int, 0, 100] = 50,
        speed: app_commands.Range[int, 0, 100] = 50,
        quality: app_commands.Range[int, 0, 100] = 50,
        tone: app_commands.Range[int, 0, 100] = 50,
        accent: app_commands.Range[int, 0, 100] = 50,
        intonation: app_commands.Range[int, 1, 4] = 1,
        lang: str = "useng",
        volume: app_commands.Range[int, 25, 300] = 165,
    ) -> None:
        voice = VoiceParams(
            pitch=pitch,
            speed=speed,
            quality=quality,
            tone=tone,
            accent=accent,
            intonation=intonation,
            lang=lang,
            volume=volume,
        )
        try:
            voice.validate()
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        if not is_voice_language_available(voice):
            await interaction.response.send_message(unsupported_language_message(voice.lang), ephemeral=True)
            return
        voice_id = normalize_voice_id(name) or "voice"
        bot.storage.save_global_user_voice(
            user_id=interaction.user.id,
            voice_id=voice_id,
            name=name,
            voice=voice,
        )
        await interaction.response.send_message(f"Saved and selected `{voice_id}`.", ephemeral=True)

    @voice_group.command(name="delete", description="Delete one of your custom voices.")
    async def voice_delete(interaction: discord.Interaction, voice_id: str) -> None:
        deleted = bot.storage.delete_voice(voice_id=voice_id, guild_id=None, owner_user_id=interaction.user.id)
        if deleted and bot.storage.get_global_user_default(interaction.user.id) == voice_id:
            bot.storage.set_global_user_default(interaction.user.id, None)
        await interaction.response.send_message("Deleted." if deleted else "No matching voice found.", ephemeral=True)

    bot.tree.add_command(voice_group)


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is required")
    load_opus()
    discord.utils.setup_logging()
    try:
        asyncio.run(run_bot(token))
    except KeyboardInterrupt:
        return


async def run_bot(token: str) -> None:
    bot = TTSModachiBot()
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def request_shutdown(signal_name: str) -> None:
        if shutdown_event.is_set():
            return
        LOGGER.info("Received %s; shutting down gracefully", signal_name)
        shutdown_event.set()

    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(shutdown_signal, request_shutdown, shutdown_signal.name)
        except (NotImplementedError, RuntimeError):
            signal.signal(
                shutdown_signal,
                lambda _signum, _frame, name=shutdown_signal.name: loop.call_soon_threadsafe(request_shutdown, name),
            )

    bot_task = asyncio.create_task(bot.start(token))
    stop_task = asyncio.create_task(shutdown_event.wait())
    try:
        done, _ = await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done and not bot_task.done():
            await bot.close()
        await bot_task
    finally:
        stop_task.cancel()
        if not bot.is_closed():
            await bot.close()


def load_opus() -> None:
    if discord.opus.is_loaded():
        return
    candidates = [
        os.environ.get("DISCORD_OPUS_LIBRARY"),
        "libopus.so.0",
        "libopus.so",
        "/usr/lib/libopus.so.0",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            discord.opus.load_opus(candidate)
        except OSError:
            continue
        if discord.opus.is_loaded():
            return
    raise RuntimeError("Discord opus library could not be loaded")


if __name__ == "__main__":
    main()

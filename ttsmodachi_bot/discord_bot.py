from __future__ import annotations

import asyncio
import logging
import os
import random
import tempfile
import urllib.parse
from pathlib import Path

import discord
from discord import app_commands

from .message_cleaner import clean_message
from .panel_tokens import create_panel_token
from .render_client import RendererClient
from .storage import Storage
from .voices import BUILTIN_VOICES, VoiceParams
from .env import env_value


LOGGER = logging.getLogger(__name__)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


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
) -> str:
    base_url = (env_value("TTSMODACHI_PANEL_URL", "https://tomo.coah80.com") or "").rstrip("/")
    token = create_panel_token(
        guild_id=guild_id,
        user_id=user_id,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    return f"{base_url}/?{urllib.parse.urlencode({'token': token})}"


async def send_voice_panel(interaction: discord.Interaction) -> None:
    assert interaction.guild is not None
    display_name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", "Discord user")
    avatar_url = str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None
    try:
        url = panel_url_for(
            interaction.guild.id,
            interaction.user.id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
    except RuntimeError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Open voice panel", url=url))
    await interaction.response.send_message("customize the voice at tomo.coah80.com!", view=view, ephemeral=True)


class GuildPlayer:
    def __init__(self, bot: "TTSModachiBot", guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: asyncio.Queue[tuple[str, VoiceParams, discord.abc.Messageable | None]] = asyncio.Queue(maxsize=20)
        self.task: asyncio.Task[None] | None = None
        self.voice_client: discord.VoiceClient | None = None

    async def connect(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel != channel:
                await self.voice_client.move_to(channel)
            return
        self.voice_client = await channel.connect(self_deaf=True)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    async def disconnect(self) -> None:
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
        self.voice_client = None

    async def enqueue(self, text: str, voice: VoiceParams, reply_to: discord.abc.Messageable | None = None) -> bool:
        try:
            self.queue.put_nowait((text, voice, reply_to))
        except asyncio.QueueFull:
            return False
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())
        return True

    def clear(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

    async def _run(self) -> None:
        while True:
            text, voice, reply_to = await self.queue.get()
            try:
                if self.voice_client is None or not self.voice_client.is_connected():
                    continue
                audio = await self.bot.renderer.render(text, voice)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
                    file.write(audio)
                    path = Path(file.name)
                await self._play_file(path)
            except Exception as error:
                LOGGER.exception("TTS playback job failed")
                if reply_to is not None:
                    await reply_to.send(f"TTS failed: {error}", delete_after=10)
            finally:
                self.queue.task_done()

    async def _play_file(self, path: Path) -> None:
        done = asyncio.Event()

        def after(error: Exception | None) -> None:
            if error:
                LOGGER.warning("Discord playback failed", exc_info=error)
            self.bot.loop.call_soon_threadsafe(done.set)

        source = discord.FFmpegPCMAudio(str(path))
        assert self.voice_client is not None
        try:
            self.voice_client.play(source, after=after)
        except Exception:
            source.cleanup()
            raise
        await done.wait()
        path.unlink(missing_ok=True)


class TTSModachiBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.storage = Storage(os.environ.get("DATABASE_PATH", "/data/ttsmodachi.sqlite3"))
        self.renderer = RendererClient(os.environ.get("RENDERER_URL", "http://tts-worker:8080"))
        self.players: dict[int, GuildPlayer] = {}
        self.sync_commands = env_bool("SYNC_COMMANDS_ON_START", True)

    async def setup_hook(self) -> None:
        register_commands(self)
        if self.sync_commands:
            await self.tree.sync()

    async def close(self) -> None:
        await self.renderer.close()
        self.storage.close()
        await super().close()

    def player_for(self, guild_id: int) -> GuildPlayer:
        player = self.players.get(guild_id)
        if player is None:
            player = GuildPlayer(self, guild_id)
            self.players[guild_id] = player
        return player

    async def on_ready(self) -> None:
        assert self.user is not None
        print(f"Logged in as {self.user} ({self.user.id})")

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return

        settings = self.storage.get_guild_settings(message.guild.id)
        if settings.ignore_bots and message.author.bot:
            return

        author_vc = message.author.voice.channel if isinstance(message.author, discord.Member) and message.author.voice else None
        in_setup_channel = settings.setup_channel_id == message.channel.id
        in_text_voice = bool(
            settings.text_in_voice
            and author_vc
            and author_vc.id == getattr(message.channel, "id", None)
        )
        if not in_setup_channel and not in_text_voice:
            return
        if settings.required_prefix is None and message.content.startswith(("/", "!", "-", ".")):
            return
        if settings.required_role_id and isinstance(message.author, discord.Member):
            if settings.required_role_id not in {role.id for role in message.author.roles}:
                return

        if author_vc is None:
            return

        player = self.player_for(message.guild.id)
        if player.voice_client is None or not player.voice_client.is_connected():
            if not settings.autojoin:
                return
            await player.connect(author_vc)
        elif settings.require_same_vc and player.voice_client.channel != author_vc:
            return

        text = clean_message(
            message.content,
            attachments=[attachment.filename for attachment in message.attachments],
            skip_emoji=settings.skip_emoji,
            repeated_chars=settings.repeated_characters,
            required_prefix=settings.required_prefix,
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

        voice_id = (
            self.storage.get_global_user_default(message.author.id)
            or self.storage.get_user_default(message.guild.id, message.author.id)
            or settings.default_voice_id
        )
        voice = self.storage.resolve_voice(voice_id, message.guild.id, message.author.id)
        queued = await player.enqueue(text, voice, message.channel)
        if not queued:
            await message.add_reaction("⏳")


def register_commands(bot: TTSModachiBot) -> None:
    @bot.tree.command(name="setup", description="Set the text channel TTSModachi reads from.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "setup_channel_id", channel.id)
        await interaction.response.send_message(f"TTSModachi will read messages from {channel.mention}.", ephemeral=True)

    @bot.tree.command(name="join", description="Join your voice channel.")
    async def join(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return
        await bot.player_for(interaction.guild.id).connect(member.voice.channel)
        await interaction.response.send_message("Joined. Type normally in the setup channel.", ephemeral=True)

    @bot.tree.command(name="leave", description="Leave the current voice channel.")
    async def leave(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await bot.player_for(interaction.guild.id).disconnect()
        await interaction.response.send_message("Left voice channel.", ephemeral=True)

    @bot.tree.command(name="skip", description="Clear queued TTS and stop current playback.")
    async def skip(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        bot.player_for(interaction.guild.id).clear()
        await interaction.response.send_message("Cleared the queue.", ephemeral=True)

    @bot.tree.command(name="settings", description="Show TTSModachi settings for this server.")
    async def settings(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        row = bot.storage.get_guild_settings(interaction.guild.id)
        setup_channel = f"<#{row.setup_channel_id}>" if row.setup_channel_id else "not set"
        required_role = f"<@&{row.required_role_id}>" if row.required_role_id else "none"
        required_prefix = row.required_prefix if row.required_prefix else "none"
        replacements = len(bot.storage.list_replacements(interaction.guild.id))
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Setup channel: {setup_channel}",
                    f"Autojoin: {format_bool(row.autojoin)}",
                    f"Require same VC: {format_bool(row.require_same_vc)}",
                    f"Ignore bots: {format_bool(row.ignore_bots)}",
                    f"Text-in-voice: {format_bool(row.text_in_voice)}",
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

    set_group = app_commands.Group(name="set", description="Change TTSModachi settings.")

    async def set_bool(interaction: discord.Interaction, column: str, label: str, value: bool) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, column, int(value))
        await interaction.response.send_message(f"{label} is now {format_bool(value)}.", ephemeral=True)

    @set_group.command(name="channel", description="Set the text channel TTSModachi reads from.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "setup_channel_id", channel.id)
        await interaction.response.send_message(f"TTSModachi will read messages from {channel.mention}.", ephemeral=True)

    @set_group.command(name="autojoin", description="Allow automatic voice join when someone sends TTS.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_autojoin(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "autojoin", "Autojoin", enabled)

    @set_group.command(name="say_name", description="Say '<name> said' before each message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_say_name(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "announce_name", "Saying names", enabled)

    @set_group.command(name="say_emoji", description="Say emoji names instead of skipping emoji.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_say_emoji(interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "skip_emoji", int(not enabled))
        await interaction.response.send_message(f"Saying emoji is now {format_bool(enabled)}.", ephemeral=True)

    @set_group.command(name="skip_emoji", description="Skip emoji within messages.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_skip_emoji(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "skip_emoji", "Skipping emoji", enabled)

    @set_group.command(name="bot_ignore", description="Ignore messages from bots and webhooks.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_bot_ignore(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "ignore_bots", "Bot ignore", enabled)

    @set_group.command(name="require_same_vc", description="Only read users in the same voice channel as the bot.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_require_same_vc(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "require_same_vc", "Require same VC", enabled)

    @set_group.command(name="text_in_voice", description="Read Discord text-in-voice channels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_text_in_voice(interaction: discord.Interaction, enabled: bool) -> None:
        await set_bool(interaction, "text_in_voice", "Text-in-voice", enabled)

    @set_group.command(name="required_prefix", description="Require a prefix before TTS messages.")
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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_required_role(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "required_role_id", role.id if role else None)
        rendered = role.mention if role else "none"
        await interaction.response.send_message(f"Required role is now {rendered}.", ephemeral=True)

    @set_group.command(name="message_length", description="Set the maximum TTS message length.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_message_length(interaction: discord.Interaction, length: app_commands.Range[int, 20, 500]) -> None:
        assert interaction.guild is not None
        bot.storage.set_guild_value(interaction.guild.id, "max_message_length", int(length))
        await interaction.response.send_message(f"Max message length is now {length}.", ephemeral=True)

    @set_group.command(name="repeated_characters", description="Clamp long repeated character runs.")
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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_server_voice(interaction: discord.Interaction, voice_id: str) -> None:
        assert interaction.guild is not None
        if not bot.storage.has_voice(voice_id, interaction.guild.id, None):
            await interaction.response.send_message("No matching server voice found. Use a built-in voice for server defaults.", ephemeral=True)
            return
        bot.storage.set_guild_value(interaction.guild.id, "default_voice_id", voice_id)
        await interaction.response.send_message(f"Server default voice is now `{voice_id}`.", ephemeral=True)

    bot.tree.add_command(set_group)

    replace_group = app_commands.Group(name="replace", description="Manage TTS pronunciation replacements.")

    @replace_group.command(name="add", description="Replace one word or phrase with another before TTS.")
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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def replacement_remove(interaction: discord.Interaction, source: str) -> None:
        assert interaction.guild is not None
        deleted = bot.storage.delete_replacement(interaction.guild.id, source.strip().lower())
        await interaction.response.send_message("Removed." if deleted else "No matching replacement found.", ephemeral=True)

    @replace_group.command(name="clear", description="Remove all pronunciation replacements.")
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

    @bot.tree.command(name="voice", description="customize the voice at tomo.coah80.com!")
    async def voice(interaction: discord.Interaction) -> None:
        await send_voice_panel(interaction)

    voice_group = app_commands.Group(name="voices", description="Manual TTSModachi voice controls.")

    @voice_group.command(name="list", description="List available voices.")
    async def voice_list(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        voices = bot.storage.list_voices(interaction.guild.id, interaction.user.id)
        rendered = ", ".join(f"`{voice_id}`" for voice_id, _ in voices[:40])
        await interaction.response.send_message(rendered or "No voices available.", ephemeral=True)

    @voice_group.command(name="use", description="Use a voice for your messages.")
    async def voice_use(interaction: discord.Interaction, voice_id: str) -> None:
        assert interaction.guild is not None
        if not bot.storage.has_voice(voice_id, interaction.guild.id, interaction.user.id):
            await interaction.response.send_message("No matching voice found.", ephemeral=True)
            return
        bot.storage.set_global_user_default(interaction.user.id, voice_id)
        await interaction.response.send_message(f"Your voice is now `{voice_id}`.", ephemeral=True)

    @voice_group.command(name="default", description="Set the server default voice.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def voice_default(interaction: discord.Interaction, voice_id: str) -> None:
        assert interaction.guild is not None
        if not bot.storage.has_voice(voice_id, interaction.guild.id, None):
            await interaction.response.send_message("No matching server voice found. Use a built-in voice for server defaults.", ephemeral=True)
            return
        bot.storage.set_guild_value(interaction.guild.id, "default_voice_id", voice_id)
        await interaction.response.send_message(f"Server default voice is now `{voice_id}`.", ephemeral=True)

    @voice_group.command(name="current", description="Show your current voice.")
    async def voice_current(interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
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
        assert interaction.guild is not None
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
        assert interaction.guild is not None
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
        voice.validate()
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
        assert interaction.guild is not None
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
    bot = TTSModachiBot()
    bot.run(token)


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

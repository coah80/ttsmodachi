from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .voices import BUILTIN_VOICES, VoiceParams


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    setup_channel_id: int | None = None
    autojoin: bool = False
    require_same_vc: bool = True
    ignore_bots: bool = True
    required_prefix: str | None = None
    required_role_id: int | None = None
    max_message_length: int = 200
    repeated_characters: int = 8
    text_in_voice: bool = True
    skip_emoji: bool = False
    announce_name: bool = True
    default_voice_id: str = "adultf"


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    setup_channel_id INTEGER,
                    autojoin INTEGER NOT NULL DEFAULT 0,
                    require_same_vc INTEGER NOT NULL DEFAULT 1,
                    ignore_bots INTEGER NOT NULL DEFAULT 1,
                    required_prefix TEXT,
                    required_role_id INTEGER,
                    max_message_length INTEGER NOT NULL DEFAULT 200,
                    repeated_characters INTEGER NOT NULL DEFAULT 8,
                    text_in_voice INTEGER NOT NULL DEFAULT 1,
                    skip_emoji INTEGER NOT NULL DEFAULT 0,
                    announce_name INTEGER NOT NULL DEFAULT 1,
                    default_voice_id TEXT NOT NULL DEFAULT 'adultf'
                )
                """
            )
            self._ensure_column("guild_settings", "repeated_characters", "INTEGER NOT NULL DEFAULT 8")
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_presets (
                    id TEXT NOT NULL,
                    guild_id INTEGER,
                    owner_user_id INTEGER,
                    name TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(id, guild_id, owner_user_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nicknames (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    PRIMARY KEY(guild_id, user_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS text_replacements (
                    guild_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    replacement TEXT NOT NULL,
                    PRIMARY KEY(guild_id, source)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    default_voice_id TEXT,
                    PRIMARY KEY(guild_id, user_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_user_settings (
                    user_id INTEGER PRIMARY KEY,
                    default_voice_id TEXT
                )
                """
            )
            self._migrate_panel_voices_to_global()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_guild_row(self, guild_id: int) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO guild_settings(
                guild_id,
                autojoin,
                require_same_vc,
                ignore_bots,
                max_message_length,
                repeated_characters,
                text_in_voice,
                skip_emoji,
                announce_name,
                default_voice_id
            )
            VALUES (?, 0, 1, 1, 200, 8, 1, 0, 1, 'adultf')
            """,
            (guild_id,),
        )

    def _migrate_panel_voices_to_global(self) -> None:
        rows = self.conn.execute(
            """
            SELECT owner_user_id, name, params_json, created_at
            FROM voice_presets
            WHERE id = 'panel' AND owner_user_id IS NOT NULL AND guild_id IS NOT NULL
            ORDER BY owner_user_id, created_at DESC
            """
        ).fetchall()
        latest_by_user: dict[int, sqlite3.Row] = {}
        for row in rows:
            latest_by_user.setdefault(int(row["owner_user_id"]), row)

        for user_id, row in latest_by_user.items():
            existing_global = self.conn.execute(
                """
                SELECT name, params_json, created_at
                FROM voice_presets
                WHERE id = 'panel' AND owner_user_id = ? AND guild_id IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            chosen = row
            if existing_global is not None and int(existing_global["created_at"]) >= int(row["created_at"]):
                chosen = existing_global
            self.conn.execute(
                "DELETE FROM voice_presets WHERE id = 'panel' AND owner_user_id = ?",
                (user_id,),
            )
            self.conn.execute(
                """
                INSERT INTO voice_presets(id, guild_id, owner_user_id, name, params_json, created_at)
                VALUES ('panel', NULL, ?, ?, ?, ?)
                """,
                (user_id, chosen["name"], chosen["params_json"], chosen["created_at"]),
            )
            self.conn.execute(
                """
                INSERT INTO global_user_settings(user_id, default_voice_id)
                VALUES (?, 'panel')
                ON CONFLICT(user_id) DO UPDATE SET default_voice_id = 'panel'
                """,
                (user_id,),
            )

    def get_guild_settings(self, guild_id: int) -> GuildSettings:
        with self.lock:
            row = self.conn.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()
            if row is None:
                return GuildSettings(guild_id=guild_id)
            return GuildSettings(
                guild_id=guild_id,
                setup_channel_id=row["setup_channel_id"],
                autojoin=bool(row["autojoin"]),
                require_same_vc=bool(row["require_same_vc"]),
                ignore_bots=bool(row["ignore_bots"]),
                required_prefix=row["required_prefix"],
                required_role_id=row["required_role_id"],
                max_message_length=int(row["max_message_length"]),
                repeated_characters=int(row["repeated_characters"]),
                text_in_voice=bool(row["text_in_voice"]),
                skip_emoji=bool(row["skip_emoji"]),
                announce_name=bool(row["announce_name"]),
                default_voice_id=row["default_voice_id"],
            )

    def set_guild_value(self, guild_id: int, column: str, value: object) -> None:
        allowed = {
            "setup_channel_id",
            "autojoin",
            "require_same_vc",
            "ignore_bots",
            "required_prefix",
            "required_role_id",
            "max_message_length",
            "repeated_characters",
            "text_in_voice",
            "skip_emoji",
            "announce_name",
            "default_voice_id",
        }
        if column not in allowed:
            raise ValueError(f"Unsupported guild setting: {column}")
        with self.lock, self.conn:
            self._ensure_guild_row(guild_id)
            self.conn.execute(f"UPDATE guild_settings SET {column} = ? WHERE guild_id = ?", (value, guild_id))

    def save_voice(
        self,
        *,
        voice_id: str,
        name: str,
        voice: VoiceParams,
        guild_id: int | None,
        owner_user_id: int | None,
    ) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "DELETE FROM voice_presets WHERE id = ? AND guild_id IS ? AND owner_user_id IS ?",
                (voice_id, guild_id, owner_user_id),
            )
            self.conn.execute(
                """
                INSERT INTO voice_presets(id, guild_id, owner_user_id, name, params_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (voice_id, guild_id, owner_user_id, name, json.dumps(voice.to_dict()), int(time.time())),
            )

    def save_global_user_voice(self, *, user_id: int, voice_id: str, name: str, voice: VoiceParams) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "DELETE FROM voice_presets WHERE id = ? AND owner_user_id = ?",
                (voice_id, user_id),
            )
            self.conn.execute(
                """
                INSERT INTO voice_presets(id, guild_id, owner_user_id, name, params_json, created_at)
                VALUES (?, NULL, ?, ?, ?, ?)
                """,
                (voice_id, user_id, name, json.dumps(voice.to_dict()), int(time.time())),
            )
            self.conn.execute(
                """
                INSERT INTO global_user_settings(user_id, default_voice_id)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET default_voice_id = excluded.default_voice_id
                """,
                (user_id, voice_id),
            )

    def delete_voice(self, *, voice_id: str, guild_id: int | None, owner_user_id: int | None) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM voice_presets WHERE id = ? AND guild_id IS ? AND owner_user_id IS ?",
                (voice_id, guild_id, owner_user_id),
            )
            return cur.rowcount > 0

    def set_user_default(self, guild_id: int, user_id: int, voice_id: str | None) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO user_settings(guild_id, user_id, default_voice_id)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET default_voice_id = excluded.default_voice_id
                """,
                (guild_id, user_id, voice_id),
            )

    def get_user_default(self, guild_id: int, user_id: int) -> str | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT default_voice_id FROM user_settings WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            return None if row is None else row["default_voice_id"]

    def set_global_user_default(self, user_id: int, voice_id: str | None) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO global_user_settings(user_id, default_voice_id)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET default_voice_id = excluded.default_voice_id
                """,
                (user_id, voice_id),
            )

    def get_global_user_default(self, user_id: int) -> str | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT default_voice_id FROM global_user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return None if row is None else row["default_voice_id"]

    def resolve_voice(self, voice_id: str | None, guild_id: int | None = None, user_id: int | None = None) -> VoiceParams:
        voice_id = voice_id or "adultf"
        if voice_id in BUILTIN_VOICES:
            return BUILTIN_VOICES[voice_id]
        with self.lock:
            row = self.conn.execute(
                """
                SELECT params_json FROM voice_presets
                WHERE id = ? AND (
                    (owner_user_id = ? AND guild_id = ?)
                    OR (owner_user_id IS NULL AND guild_id = ?)
                    OR (owner_user_id = ? AND guild_id IS NULL)
                )
                ORDER BY
                    (owner_user_id = ? AND guild_id = ?) DESC,
                    (owner_user_id = ? AND guild_id IS NULL) DESC,
                    (owner_user_id IS NULL AND guild_id = ?) DESC
                LIMIT 1
                """,
                (voice_id, user_id, guild_id, guild_id, user_id, user_id, guild_id, user_id, guild_id),
            ).fetchone()
        if row is None:
            return BUILTIN_VOICES["adultf"]
        return VoiceParams.from_mapping(json.loads(row["params_json"]))

    def has_voice(self, voice_id: str, guild_id: int | None = None, user_id: int | None = None) -> bool:
        if voice_id in BUILTIN_VOICES:
            return True
        with self.lock:
            row = self.conn.execute(
                """
                SELECT 1 FROM voice_presets
                WHERE id = ? AND (
                    (owner_user_id = ? AND guild_id = ?)
                    OR (owner_user_id IS NULL AND guild_id = ?)
                    OR (owner_user_id = ? AND guild_id IS NULL)
                )
                LIMIT 1
                """,
                (voice_id, user_id, guild_id, guild_id, user_id),
            ).fetchone()
        return row is not None

    def list_voices(self, guild_id: int, user_id: int) -> list[tuple[str, str]]:
        voices = [(voice_id, voice_id) for voice_id in BUILTIN_VOICES]
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT id, name FROM voice_presets
                WHERE (guild_id = ? AND owner_user_id IS NULL)
                   OR (guild_id = ? AND owner_user_id = ?)
                   OR (guild_id IS NULL AND owner_user_id = ?)
                ORDER BY name
                """,
                (guild_id, guild_id, user_id, user_id),
            ).fetchall()
        voices.extend((row["id"], row["name"]) for row in rows)
        return voices

    def get_nickname(self, guild_id: int, user_id: int) -> str | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT name FROM nicknames WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            return None if row is None else row["name"]

    def set_nickname(self, guild_id: int, user_id: int, name: str | None) -> None:
        with self.lock, self.conn:
            if name:
                self.conn.execute(
                    """
                    INSERT INTO nicknames(guild_id, user_id, name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET name = excluded.name
                    """,
                    (guild_id, user_id, name),
                )
            else:
                self.conn.execute("DELETE FROM nicknames WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

    def set_replacement(self, guild_id: int, source: str, replacement: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO text_replacements(guild_id, source, replacement)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, source) DO UPDATE SET replacement = excluded.replacement
                """,
                (guild_id, source, replacement),
            )

    def delete_replacement(self, guild_id: int, source: str) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM text_replacements WHERE guild_id = ? AND source = ?",
                (guild_id, source),
            )
            return cur.rowcount > 0

    def clear_replacements(self, guild_id: int) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM text_replacements WHERE guild_id = ?", (guild_id,))
            return cur.rowcount

    def list_replacements(self, guild_id: int) -> list[tuple[str, str]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT source, replacement FROM text_replacements WHERE guild_id = ? ORDER BY source LIMIT 50",
                (guild_id,),
            ).fetchall()
        return [(row["source"], row["replacement"]) for row in rows]

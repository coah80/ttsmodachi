from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .env import env_value


@dataclass(frozen=True)
class PanelSession:
    guild_id: int
    user_id: int
    expires_at: int
    issued_at_ms: int
    display_name: str | None = None
    avatar_url: str | None = None


def panel_signing_key() -> str | None:
    return (
        env_value("TTSMODACHI_PANEL_SIGNING_KEY")
        or env_value("TTSMODACHI_PANEL_TOKEN")
        or os.environ.get("DISCORD_TOKEN")
    )


def create_panel_token(
    *,
    guild_id: int,
    user_id: int,
    display_name: str | None = None,
    avatar_url: str | None = None,
    ttl_seconds: int = 86400,
    issued_at_ms: int | None = None,
) -> str:
    key = panel_signing_key()
    if not key:
        raise RuntimeError("TTSMODACHI_PANEL_SIGNING_KEY is required for voice panel links")

    now = int(time.time())
    if issued_at_ms is None:
        issued_at_ms = time.time_ns() // 1_000_000
    payload = {
        "guild_id": guild_id,
        "user_id": user_id,
        "expires_at": now + ttl_seconds,
        "issued_at_ms": issued_at_ms,
    }
    if display_name:
        payload["display_name"] = display_name[:100]
    if avatar_url:
        payload["avatar_url"] = avatar_url[:500]
    body = _encode_json(payload)
    signature = _sign(body, key)
    return f"{body}.{signature}"


def parse_panel_token(token: str | None) -> PanelSession:
    key = panel_signing_key()
    if not key:
        raise ValueError("Panel signing key is not configured")
    if not token or "." not in token:
        raise ValueError("Panel token is missing")

    body, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _sign(body, key)):
        raise ValueError("Panel token signature is invalid")

    payload = _decode_json(body)
    expires_at = int(payload["expires_at"])
    if expires_at < int(time.time()):
        raise ValueError("Panel token expired")

    return PanelSession(
        guild_id=int(payload["guild_id"]),
        user_id=int(payload["user_id"]),
        expires_at=expires_at,
        issued_at_ms=int(payload.get("issued_at_ms", 0)),
        display_name=str(payload["display_name"]) if payload.get("display_name") else None,
        avatar_url=str(payload["avatar_url"]) if payload.get("avatar_url") else None,
    )


def _sign(body: str, key: str) -> str:
    digest = hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _encode_json(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64encode(raw)


def _decode_json(body: str) -> dict[str, Any]:
    return json.loads(_b64decode(body).decode("utf-8"))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

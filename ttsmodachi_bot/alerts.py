from __future__ import annotations

import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


DEFAULT_ALERT_TYPES = {
    "cheer",
    "cheerpurchase",
    "cheerlatest",
    "cheerpurchaselatest",
}


@dataclass(frozen=True)
class AlertEvent:
    id: str
    source: str
    install_id: str
    channel: str
    listener: str
    kind: str
    user: str
    amount: str
    currency: str
    message: str
    raw: dict[str, Any] = field(repr=False)

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "source": self.source,
            "installId": self.install_id,
            "channel": self.channel,
            "listener": self.listener,
            "kind": self.kind,
            "user": self.user,
            "amount": self.amount,
            "currency": self.currency,
            "message": self.message,
        }


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


class RecentEventIds:
    def __init__(self, ttl_seconds: int, max_items: int = 512) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.items: dict[str, float] = {}

    def seen(self, event_id: str) -> bool:
        now = time.monotonic()
        self.prune(now)
        if event_id in self.items:
            self.items[event_id] = now
            return True
        self.items[event_id] = now
        if len(self.items) > self.max_items:
            oldest = sorted(self.items.items(), key=lambda item: item[1])
            for key, _ in oldest[: len(self.items) - self.max_items]:
                self.items.pop(key, None)
        return False

    def prune(self, now: float | None = None) -> None:
        now = now or time.monotonic()
        cutoff = now - self.ttl_seconds
        expired = [key for key, seen_at in self.items.items() if seen_at < cutoff]
        for key in expired:
            self.items.pop(key, None)


def parse_alert_types(value: str | None) -> set[str]:
    if not value:
        return set(DEFAULT_ALERT_TYPES)
    return {normalize_type(part) for part in value.split(",") if part.strip()}


def normalize_type(value: Any) -> str:
    return str(value or "").strip().replace("_", "").replace("-", "").lower()


def alert_matches(alert: AlertEvent, allowed_types: set[str]) -> bool:
    if not allowed_types:
        return True
    candidates = {
        normalize_type(alert.listener),
        normalize_type(alert.kind),
        normalize_type(f"{alert.kind}-latest"),
    }
    return bool(candidates & allowed_types)


def normalize_alert(raw: dict[str, Any], source: str) -> AlertEvent:
    raw = as_mapping(raw)
    detail = as_mapping(raw.get("detail"))
    topic = as_text(raw.get("topic") or detail.get("topic"))
    listener = as_text(raw.get("listener") or detail.get("listener") or raw.get("type"))
    event_data = as_mapping(raw.get("event") or detail.get("event"))
    channel_data = as_mapping(raw.get("channel") or detail.get("channel"))

    if not event_data:
        event_data = raw

    install_id = as_text(raw.get("installId") or raw.get("install_id") or detail.get("installId"))
    channel = as_text(first_value(channel_data, ("username", "name", "login", "id", "_id", "channelId")))
    kind = event_kind(listener, topic, event_data)
    user = as_text(
        first_value(event_data, ("displayName", "display_name", "name", "username", "sender", "login"))
    ) or "someone"
    amount = amount_text(first_value(event_data, ("amount", "bits", "quantity", "count")))
    currency = as_text(first_value(event_data, ("currency", "symbol"))) or "bits"
    message = as_text(first_value(event_data, ("message", "text", "comment")))
    event_id = as_text(first_value(event_data, ("activityId", "_id", "id", "transactionId", "_ttsmodachiEventId"))) or stable_event_hash(
        source,
        install_id,
        listener,
        kind,
        user,
        amount,
        message,
    )

    return AlertEvent(
        id=event_id,
        source=source,
        install_id=install_id,
        channel=channel,
        listener=listener or kind,
        kind=kind,
        user=user,
        amount=amount or "0",
        currency=currency,
        message=message,
        raw=raw,
    )


def event_kind(listener: str, topic: str, event_data: dict[str, Any]) -> str:
    if listener:
        return listener.removesuffix("-latest")
    event_type = as_text(event_data.get("type"))
    if event_type:
        return event_type
    if topic == "channel.tips":
        return "tip"
    return "event"


def build_speech_text(
    alert: AlertEvent,
    message_template: str | None = None,
    no_message_template: str | None = None,
) -> str:
    context = SafeFormatDict(
        user=alert.user,
        amount=alert.amount,
        currency=alert.currency,
        message=alert.message,
        kind=alert.kind,
        listener=alert.listener,
        source=alert.source,
    )
    template = message_template if alert.message else no_message_template
    if not template:
        template = default_template(alert, bool(alert.message))
    return " ".join(template.format_map(context).split())


def default_template(alert: AlertEvent, has_message: bool) -> str:
    kind = normalize_type(alert.kind)
    if kind == "tip":
        if has_message:
            return "{user} tipped {amount} {currency}. {message}"
        return "{user} tipped {amount} {currency}."
    if kind == "cheerpurchase":
        return "{user} bought {amount} bits."
    if has_message:
        return "{user} cheered {amount} bits. {message}"
    return "{user} cheered {amount} bits."


def as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return amount_text(value)
    return str(value).strip()


def amount_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:g}"
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else f"{number:g}"


def first_value(value: Any, keys: tuple[str, ...], depth: int = 0) -> Any:
    if depth > 8:
        return None
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] not in (None, ""):
                return value[key]
        for item in value.values():
            found = first_value(item, keys, depth + 1)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = first_value(item, keys, depth + 1)
            if found not in (None, ""):
                return found
    return None


def stable_event_hash(*parts: str) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()

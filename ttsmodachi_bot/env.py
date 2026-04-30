from __future__ import annotations

import os


def legacy_env_name(name: str) -> str:
    if name.startswith("TTSMODACHI_"):
        return "TALKMODACHI_" + name.removeprefix("TTSMODACHI_")
    return name


def env_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    legacy_name = legacy_env_name(name)
    if legacy_name != name:
        legacy_value = os.environ.get(legacy_name)
        if legacy_value:
            return legacy_value
    return default


def env_int(name: str, default: int) -> int:
    return int(env_value(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(env_value(name, str(default)))


def env_setdefault(name: str, default: str) -> None:
    if os.environ.get(name):
        return
    legacy_name = legacy_env_name(name)
    if legacy_name != name and os.environ.get(legacy_name):
        os.environ[name] = os.environ[legacy_name]
        return
    os.environ[name] = default

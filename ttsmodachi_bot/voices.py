from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any


LANG_TO_ID = {
    "useng": 1,
    "eueng": 1,
    "fr": 2,
    "de": 3,
    "it": 4,
    "es": 5,
    "jp": 1,
    "kr": 1,
}

LANG_TO_ROM = {
    "useng": "US",
    "eueng": "EU",
    "fr": "EU",
    "de": "EU",
    "it": "EU",
    "es": "EU",
    "jp": "JP",
    "kr": "KR",
}

TEXT_LIMITS = {
    "jp": 1024,
}

DEFAULT_TEXT_LIMIT = 2000


@dataclass(frozen=True)
class VoiceParams:
    pitch: int = 50
    speed: int = 50
    quality: int = 50
    tone: int = 50
    accent: int = 50
    intonation: int = 1
    lang: str = "useng"
    volume: int = 165

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "VoiceParams":
        values = values or {}
        voice = cls(
            pitch=int(values.get("pitch", 50)),
            speed=int(values.get("speed", 50)),
            quality=int(values.get("quality", 50)),
            tone=int(values.get("tone", 50)),
            accent=int(values.get("accent", 50)),
            intonation=int(values.get("intonation", 1)),
            lang=str(values.get("lang", "useng")),
            volume=int(values.get("volume", 165)),
        )
        voice.validate()
        return voice

    def validate(self) -> None:
        numeric_values = {
            "pitch": self.pitch,
            "speed": self.speed,
            "quality": self.quality,
            "tone": self.tone,
            "accent": self.accent,
        }
        invalid = [name for name, value in numeric_values.items() if not 0 <= value <= 100]
        if invalid:
            raise ValueError(f"Voice parameter out of range: {', '.join(invalid)}")
        if not 25 <= self.volume <= 300:
            raise ValueError("Volume must be between 25 and 300")
        if self.intonation not in {1, 2, 3, 4}:
            raise ValueError("Intonation must be 1, 2, 3, or 4")
        if self.lang not in LANG_TO_ID:
            raise ValueError(f"Unsupported language: {self.lang}")

    def engine_intonation(self) -> int:
        return self.intonation - 1

    def lang_id(self) -> int:
        return LANG_TO_ID[self.lang]

    def rom(self) -> str:
        return LANG_TO_ROM[self.lang]

    def text_limit(self) -> int:
        return TEXT_LIMITS.get(self.lang, DEFAULT_TEXT_LIMIT)

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)

    def cache_fragment(self) -> str:
        parts = (
            self.lang,
            str(self.pitch),
            str(self.speed),
            str(self.quality),
            str(self.tone),
            str(self.accent),
            str(self.intonation),
            str(self.volume),
        )
        return ":".join(parts)


BUILTIN_VOICES: dict[str, VoiceParams] = {
    "youngm": VoiceParams(accent=25, intonation=1, pitch=60, quality=72, speed=59, tone=25),
    "youngf": VoiceParams(accent=25, intonation=1, pitch=83, quality=78, speed=65, tone=25),
    "adultm": VoiceParams(accent=25, intonation=1, pitch=33, quality=39, speed=52, tone=25),
    "adultf": VoiceParams(accent=25, intonation=1, pitch=68, quality=58, speed=39, tone=25),
    "oldm": VoiceParams(accent=25, intonation=1, pitch=25, quality=39, speed=29, tone=15),
    "oldf": VoiceParams(accent=42, intonation=1, pitch=67, quality=69, speed=18, tone=12),
}


def cache_key(text: str, voice: VoiceParams, mode: str, engine_version: str) -> str:
    payload = "\0".join([engine_version, mode, text, voice.cache_fragment()])
    return sha256(payload.encode("utf-8")).hexdigest()

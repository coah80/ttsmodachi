from __future__ import annotations

from dataclasses import dataclass


ENGINE_TL3DS = "tl3ds"

@dataclass(frozen=True)
class EngineInfo:
    id: str
    label: str
    experimental: bool = False


ENGINES: dict[str, EngineInfo] = {
    ENGINE_TL3DS: EngineInfo(id=ENGINE_TL3DS, label="Tomodachi Life 3DS"),
}

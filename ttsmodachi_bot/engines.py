from __future__ import annotations

from dataclasses import dataclass


ENGINE_TL3DS = "tl3ds"
ENGINE_LTD_SWITCH = "ltd-switch"


@dataclass(frozen=True)
class EngineInfo:
    id: str
    label: str
    experimental: bool = False


ENGINES: dict[str, EngineInfo] = {
    ENGINE_TL3DS: EngineInfo(id=ENGINE_TL3DS, label="Tomodachi Life 3DS"),
    ENGINE_LTD_SWITCH: EngineInfo(id=ENGINE_LTD_SWITCH, label="Living the Dream", experimental=True),
}

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engines import ENGINE_LTD_SWITCH
from .voices import VoiceParams


BASE_MAIN_BUILD_ID = "56BF85BD535413464CB75BB6C2683B6711E0BC0B000000000000000000000000"


@dataclass(frozen=True)
class LtdRenderRequest:
    text: str
    voice: VoiceParams
    mode: str = "text"


@dataclass(frozen=True)
class LtdTarget:
    title_id: str
    version: int
    main_build_id: str
    program_nca_id: str


BASE_TARGET = LtdTarget(
    title_id="010051f0207b2000",
    version=0,
    main_build_id=BASE_MAIN_BUILD_ID,
    program_nca_id="2e88713715d1d950ece6ce679a2fd456",
)


class LtdSwitchWorker:
    def __init__(self, *, ryubing_path: Path, game_path: Path, target: LtdTarget = BASE_TARGET) -> None:
        self.ryubing_path = ryubing_path
        self.game_path = game_path
        self.target = target

    def render(self, request: LtdRenderRequest) -> bytes:
        if request.voice.engine != ENGINE_LTD_SWITCH:
            raise ValueError(f"LTD worker requires {ENGINE_LTD_SWITCH} voices")
        raise NotImplementedError("ltd-switch render bridge is not implemented yet")

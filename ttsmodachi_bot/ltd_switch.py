from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
import wave
import csv
import math
import sys
import signal
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Event, RLock, Thread

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


@dataclass(frozen=True)
class LtdAddressTable:
    guest_base: str
    request_addr: str
    request_text_prep_addr: str
    text_dispatcher_addr: str
    capture_addrs: str
    pcm_dump_addrs: str
    consumer_capture_addrs: str
    consumer_kick_addr: str
    consumer_kick_max: str
    consumer_kick_interval_ms: str
    manager_global_addr: str
    manager_inner_offset: str
    request_object_offset: str
    text_buffer_offset: str
    text_pointer_offset: str
    text_length_offset: str
    ready_flag_offset: str
    alternate_text_flag_offset: str
    voice_context_offset: str

    @property
    def default_block_trace_addrs(self) -> str:
        return ",".join(
            (
                self.request_addr,
                self.request_text_prep_addr,
                "0x43f704",
                self.pcm_dump_addrs,
                "0x4659d8",
                self.capture_addrs,
            )
        )


BASE_TARGET = LtdTarget(
    title_id="010051f0207b2000",
    version=0,
    main_build_id=BASE_MAIN_BUILD_ID,
    program_nca_id="2e88713715d1d950ece6ce679a2fd456",
)

BASE_ADDRESS_TABLE = LtdAddressTable(
    guest_base="0x8506000",
    request_addr="0x4445cc",
    request_text_prep_addr="0x444660",
    text_dispatcher_addr="0x443cec",
    capture_addrs="0x600f04,0x600efc",
    pcm_dump_addrs="0x465714",
    consumer_capture_addrs="0x465598",
    consumer_kick_addr="0x465598",
    consumer_kick_max="8",
    consumer_kick_interval_ms="20",
    manager_global_addr="0x32ccde0",
    manager_inner_offset="0xda0",
    request_object_offset="0x1860",
    text_buffer_offset="0xcc",
    text_pointer_offset="0xc0",
    text_length_offset="0xc8",
    ready_flag_offset="0x8d8",
    alternate_text_flag_offset="0x8d0",
    voice_context_offset="0x8e8",
)


class LtdSwitchWorker:
    def __init__(
        self,
        *,
        ryubing_path: Path,
        game_path: Path,
        data_dir: Path | None = None,
        work_dir: Path | None = None,
        dotnet_root: str | None = None,
        timeout_seconds: float = 150.0,
        target: LtdTarget = BASE_TARGET,
        addresses: LtdAddressTable = BASE_ADDRESS_TABLE,
    ) -> None:
        self.ryubing_path = ryubing_path.expanduser().resolve()
        self.game_path = game_path.expanduser().resolve()
        self.data_dir = (data_dir or Path("ltd-work/ryubing-data")).expanduser().resolve()
        self.work_dir = (work_dir or Path("ltd-work/ltd-renderer")).expanduser().resolve()
        self.dotnet_root = dotnet_root or os.environ.get("DOTNET_ROOT", "/opt/homebrew/Cellar/dotnet/10.0.105/libexec")
        self.timeout_seconds = timeout_seconds
        self.target = target
        self.addresses = addresses
        self.warm_enabled = env_bool_default("TTSMODACHI_LTD_WARM", False)
        self.prewarm_enabled = env_bool_default("TTSMODACHI_LTD_PREWARM", True)
        self._warm_lock = RLock()
        self._warm_process: subprocess.Popen[bytes] | None = None
        self._warm_log_file = None
        self._warm_dir: Path | None = None
        self._warm_dump_dir: Path | None = None
        self._warm_text_file: Path | None = None
        self._warm_audio_trace: Path | None = None
        self._warm_block_trace: Path | None = None
        self._warm_appliance_trace: Path | None = None
        self._warm_appliance_pcm_dump: Path | None = None
        self._warm_appliance_pcm_ack_file: Path | None = None
        self._warm_appliance_pcm_sample_rate = int(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_SAMPLE_RATE", "32000"))
        self._warm_no_present_file: Path | None = None
        self._warm_discard_present_file: Path | None = None
        self._warm_log_path: Path | None = None
        self._warm_started_at: float | None = None
        self._warm_last_activity_at: float | None = None
        self._warm_last_render_ms: float | None = None
        self._warm_render_count = 0
        self._warm_active_job_count = 0
        self._warm_paused = False
        self._warm_resume_count = 0
        self._warm_restart_count = 0
        self._warm_last_recovery_reason: str | None = None
        self._warm_last_error: str | None = None
        self._warm_idle_suspend_seconds = float(os.environ.get("TTSMODACHI_LTD_IDLE_SUSPEND_SECONDS", os.environ.get("TTSMODACHI_IDLE_SUSPEND_SECONDS", "10")))
        self._warm_idle_resume_timeout = float(os.environ.get("TTSMODACHI_LTD_IDLE_RESUME_TIMEOUT_MS", os.environ.get("TTSMODACHI_IDLE_RESUME_TIMEOUT_MS", "1000"))) / 1000
        self._warm_governor_stop = Event()
        self._warm_governor: Thread | None = None
        self._warm_prewarmer: Thread | None = None
        self._warm_prewarm_started_at: float | None = None
        self._warm_prewarm_finished_at: float | None = None
        self._warm_prewarm_error: str | None = None

    def render(self, request: LtdRenderRequest) -> bytes:
        if request.voice.engine != ENGINE_LTD_SWITCH:
            raise ValueError(f"LTD worker requires {ENGINE_LTD_SWITCH} voices")
        if request.mode != "text":
            raise ValueError("ltd-switch currently supports text renders only")
        self._validate_runtime_paths()

        text = request.text.replace("\n", " ").strip()
        if not text:
            raise ValueError("Cannot render empty LTD text")
        max_text_bytes = int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96"))
        if len(text.encode("utf-8")) > max_text_bytes:
            raise ValueError(f"LTD text is longer than {max_text_bytes} UTF-8 bytes")

        if self.warm_enabled:
            with self._warm_lock:
                return self._render_warm(text, max_text_bytes, request.voice)

        out_dir = self.work_dir / f"render-{uuid.uuid4().hex}"
        dump_dir = out_dir / "audio-dumps"
        live_input = out_dir / "live-input.txt"
        live_touch = out_dir / "live-touch.txt"
        log_path = out_dir / "ryubing.log"
        audio_trace = out_dir / "audio.csv"
        capture_mode = os.environ.get("TTSMODACHI_LTD_CAPTURE_MODE", "voice-only").strip().lower()
        capture_mixed = capture_mode in {"mixed", "final", "sink"} or env_bool("TTSMODACHI_LTD_ENABLE_MIX_CAPTURE")
        appliance_mode = env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)
        dsp_trace_enabled = ltd_dsp_trace_enabled(appliance_mode)
        output_dir = out_dir / "output-dumps"
        output_trace = out_dir / "output-audio.csv"
        input_trace = out_dir / "input.csv"
        block_trace = out_dir / "block-trace.csv"
        appliance_trace = out_dir / "appliance.csv"
        appliance_pcm_dump = out_dir / "appliance.pcm"
        appliance_pcm_sample_rate = int(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_SAMPLE_RATE", "32000"))
        appliance_pcm_seconds = max(1.0, min(float(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MAX_SECONDS", "5.0")), len(text.encode("utf-8")) / 14.0))
        appliance_pcm_max_bytes = int(appliance_pcm_sample_rate * 2 * appliance_pcm_seconds)
        try:
            dump_dir.mkdir(parents=True, exist_ok=True)
            if capture_mixed:
                output_dir.mkdir(parents=True, exist_ok=True)
            boot_input_enabled = ltd_boot_input_enabled(appliance_mode)
            if boot_input_enabled:
                live_input.write_text("\n")
                live_touch.write_text("\n")

            env = os.environ.copy()
            env.update(
                {
                    "DOTNET_ROOT": self.dotnet_root,
                    "RYUJINX_HEADLESS_SWKBD_AUTO_ACCEPT": "true",
                    "RYUJINX_HEADLESS_SWKBD_TEXTS": "Cole|TTSmodachi|Ryujinx|Tomodachi",
                    "RYUJINX_TTSMODACHI_DISABLE_HYPERVISOR": "true",
                    "RYUJINX_TTSMODACHI_DUMMY_AUDIO": ltd_dummy_audio_value(appliance_mode),
                    "RYUJINX_TTSMODACHI_MUTE_DEVICE_SINK": ltd_mute_device_sink_value(appliance_mode),
                    "RYUJINX_TTSMODACHI_NO_PRESENT": os.environ.get("TTSMODACHI_LTD_NO_PRESENT", "false"),
                    "RYUJINX_TTSMODACHI_DISCARD_PRESENT": os.environ.get("TTSMODACHI_LTD_DISCARD_PRESENT", "true" if appliance_mode else "false"),
                    "RYUJINX_TTSMODACHI_WINDOW_WIDTH": os.environ.get("TTSMODACHI_LTD_WINDOW_WIDTH", "320" if appliance_mode else ""),
                    "RYUJINX_TTSMODACHI_WINDOW_HEIGHT": os.environ.get("TTSMODACHI_LTD_WINDOW_HEIGHT", "180" if appliance_mode else ""),
                    "RYUJINX_TTSMODACHI_LOW_DPI_WINDOW": os.environ.get("TTSMODACHI_LTD_LOW_DPI_WINDOW", "true" if appliance_mode else "false"),
                    "RYUJINX_TTSMODACHI_GUEST_TRACE_BASE": self.addresses.guest_base,
                    "RYUJINX_TTSMODACHI_BLOCK_TRACE": str(block_trace),
                    "RYUJINX_TTSMODACHI_BLOCK_TRACE_MAX_EVENTS": "256",
                    "RYUJINX_TTSMODACHI_MEMORY_WRITE_TRACE": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_TRACE", ""),
                    "RYUJINX_TTSMODACHI_MEMORY_WRITE_RANGES": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_RANGES", ""),
                    "RYUJINX_TTSMODACHI_MEMORY_WRITE_MAX_EVENTS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_MAX_EVENTS", "20000"),
                    "RYUJINX_TTSMODACHI_MEMORY_WRITE_START_SECONDS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_START_SECONDS", ""),
                    "RYUJINX_TTSMODACHI_MEMORY_WRITE_DURATION_SECONDS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_DURATION_SECONDS", ""),
                }
            )
            if boot_input_enabled:
                env.update(
                    {
                        "RYUJINX_TTSMODACHI_AUTO_A": "true",
                        "RYUJINX_TTSMODACHI_AUTO_A_START_FRAME": os.environ.get("TTSMODACHI_LTD_AUTO_A_START_FRAME", "300"),
                        "RYUJINX_TTSMODACHI_AUTO_A_INTERVAL_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_INTERVAL_FRAMES", "60"),
                        "RYUJINX_TTSMODACHI_AUTO_A_DURATION_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_DURATION_FRAMES", "6"),
                        "RYUJINX_TTSMODACHI_TOUCH_SCRIPT": os.environ.get("TTSMODACHI_LTD_TOUCH_SCRIPT", build_touch_script()),
                        "RYUJINX_TTSMODACHI_TOUCH_FILE": str(live_touch),
                        "RYUJINX_TTSMODACHI_INPUT_FILE": str(live_input),
                    }
                )
            if dsp_trace_enabled:
                env.update(
                    {
                        "RYUJINX_TTSMODACHI_AUDIO_TRACE": str(audio_trace),
                        "RYUJINX_TTSMODACHI_AUDIO_TRACE_FORMATS": "PcmInt16,PcmFloat",
                        "RYUJINX_TTSMODACHI_AUDIO_TRACE_MIN_PEAK": "0.001",
                        "RYUJINX_TTSMODACHI_AUDIO_TRACE_MAX_EVENTS": "10000",
                        "RYUJINX_TTSMODACHI_AUDIO_DUMP_DIR": str(dump_dir),
                        "RYUJINX_TTSMODACHI_AUDIO_DUMP_MAX_SECONDS": "5",
                    }
                )
            if appliance_mode:
                env.update(
                    {
                        "RYUJINX_TTSMODACHI_APPLIANCE": "true",
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT": text,
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_MAX_BYTES": str(max_text_bytes),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRACE": str(appliance_trace),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_MAX_EVENTS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_MAX_EVENTS", "10000"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_POLLS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_POLLS", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_CONSUMER_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_CONSUMER_REGISTERS", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_REQUEST_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_REQUEST_REGISTERS", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_TRACE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ADDRS", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_TRACE_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ONCE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_DIR", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_BYTES", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_REGISTERS", "0,1,2,3,19,20,21,22,23,24,29,30,31"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_DIR", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_BYTES", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_REGISTERS", "0,19,21,22"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_FILE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_FILE", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_LOAD": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_LOAD", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_SAVE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_SAVE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_MEMORY_PATCH_FILE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_FILE", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_MEMORY_PATCH_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_ONCE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_DIR", ""),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_BYTES", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_ONCE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_INTERVAL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_INTERVAL_MS", "1200"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_REPEATS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_REPEATS", "1"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_ON_CAPTURE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_RESTORE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESTORE", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PARK_ON_CAPTURE_READY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_ON_CAPTURE_READY", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_CONTEXT_CAPTURE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_CONTEXT_CAPTURE", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_CONTEXT_REPLAY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_CONTEXT_REPLAY", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_CONTEXT_REPLAY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_CONTEXT_REPLAY", "false"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TRAMPOLINE_RETURN_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRAMPOLINE_RETURN_ADDR", "0x3004"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_RESUME_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESUME_ADDR", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_CAPTURE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS", self.addresses.consumer_capture_addrs),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR", self.addresses.consumer_kick_addr),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_MAX": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX", self.addresses.consumer_kick_max),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_INTERVAL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_INTERVAL_MS", self.addresses.consumer_kick_interval_ms),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PARK": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK", "true"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PARK_POLL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_POLL_MS", "25"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PARK_MAX_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_MAX_MS", "0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_HOST_PARK_SLEEP_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_HOST_PARK_SLEEP_MS", "8"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_ADDR", self.addresses.request_addr),
                        "RYUJINX_TTSMODACHI_APPLIANCE_CAPTURE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CAPTURE_ADDRS", self.addresses.capture_addrs),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_DUMP_ADDRS", self.addresses.pcm_dump_addrs),
                        "RYUJINX_TTSMODACHI_APPLIANCE_MANAGER_GLOBAL_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MANAGER_GLOBAL_ADDR", self.addresses.manager_global_addr),
                        "RYUJINX_TTSMODACHI_APPLIANCE_MANAGER_INNER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MANAGER_INNER_OFFSET", self.addresses.manager_inner_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_OBJECT_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_OBJECT_OFFSET", self.addresses.request_object_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_BUFFER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_BUFFER_OFFSET", self.addresses.text_buffer_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_POINTER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_POINTER_OFFSET", self.addresses.text_pointer_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_LENGTH_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_LENGTH_OFFSET", self.addresses.text_length_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_READY_FLAG_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_READY_FLAG_OFFSET", self.addresses.ready_flag_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_ALT_TEXT_FLAG_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_ALT_TEXT_FLAG_OFFSET", self.addresses.alternate_text_flag_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_VOICE_CONTEXT_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_VOICE_CONTEXT_OFFSET", self.addresses.voice_context_offset),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP": str(appliance_pcm_dump),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP_MAX_BYTES": os.environ.get(
                            "TTSMODACHI_LTD_APPLIANCE_PCM_MAX_BYTES",
                            str(appliance_pcm_max_bytes),
                        ),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_SAMPLE_RATE": str(appliance_pcm_sample_rate),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_MIN_SECONDS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MIN_SECONDS", "1.0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_MAX_SECONDS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MAX_SECONDS", "5.0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_TEXT_BYTES_PER_SECOND": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_TEXT_BYTES_PER_SECOND", "14.0"),
                        "RYUJINX_TTSMODACHI_APPLIANCE_PCM_CAPTURE_TEXT_BYTES_PER_SECOND": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_CAPTURE_TEXT_BYTES_PER_SECOND", "14.0"),
                        "RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS": os.environ.get(
                            "TTSMODACHI_LTD_APPLIANCE_BLOCK_TRACE_ADDRS",
                            self.addresses.default_block_trace_addrs,
                        ),
                    }
                )
            else:
                env.update(
                    {
                        "RYUJINX_TTSMODACHI_AUTO_A": "true",
                        "RYUJINX_TTSMODACHI_AUTO_A_START_FRAME": os.environ.get("TTSMODACHI_LTD_AUTO_A_START_FRAME", "300"),
                        "RYUJINX_TTSMODACHI_AUTO_A_INTERVAL_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_INTERVAL_FRAMES", "60"),
                        "RYUJINX_TTSMODACHI_AUTO_A_DURATION_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_DURATION_FRAMES", "6"),
                        "RYUJINX_TTSMODACHI_TOUCH_SCRIPT": build_touch_script(),
                        "RYUJINX_TTSMODACHI_TOUCH_FILE": str(live_touch),
                        "RYUJINX_TTSMODACHI_INPUT_FILE": str(live_input),
                        "RYUJINX_TTSMODACHI_INPUT_TRACE": str(input_trace),
                        "RYUJINX_TTSMODACHI_TEXT_INJECT": text,
                        "RYUJINX_TTSMODACHI_TEXT_INJECT_ADDR": os.environ.get("RYUJINX_TTSMODACHI_TEXT_INJECT_ADDR", self.addresses.request_text_prep_addr),
                        "RYUJINX_TTSMODACHI_TEXT_INJECT_MAX_BYTES": str(max_text_bytes),
                        "RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS": os.environ.get("TTSMODACHI_LTD_BLOCK_TRACE_ADDRS", self.addresses.request_text_prep_addr),
                    }
                )
            if capture_mixed:
                env.update(
                    {
                        "RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_DIR": str(output_dir),
                        "RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_TRACE": str(output_trace),
                        "RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_MIN_PEAK": os.environ.get("RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_MIN_PEAK", "512"),
                        "RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_MAX_SECONDS": os.environ.get("RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_MAX_SECONDS", "8"),
                    }
                )
            memory_manager_mode = os.environ.get("TTSMODACHI_LTD_MEMORY_MANAGER_MODE", "HostMappedUnsafe")
            command = [
                "./build/Ryujinx",
                "--no-gui",
                "--root-data-dir",
                str(self.data_dir),
                "--disable-file-logging",
                "--ignore-missing-services",
                "--skip-user-profiles-manager",
                "--system-language",
                "AmericanEnglish",
                "--system-region",
                "USA",
                "--use-hypervisor",
                "false",
                "--memory-manager-mode",
                memory_manager_mode,
                str(self.game_path),
            ]
            if env_bool_default("TTSMODACHI_LTD_DISABLE_SHADER_CACHE", appliance_mode):
                command.insert(-1, "--disable-shader-cache")
            apply_ltd_command_tuning(command)
            if memory_manager_mode.lower() == "softwarepagetable" or env_bool("TTSMODACHI_LTD_DISABLE_PTC"):
                command.insert(-1, "--disable-ptc")
            if env_bool("TTSMODACHI_LTD_DEBUG_LOGS"):
                command.insert(-1, "--enable-debug-logs")
            started = time.monotonic()
            dump: tuple[Path, int] | None = None
            with log_path.open("wb") as log_file:
                process = subprocess.Popen(command, cwd=self.ryubing_path, env=env, stdout=log_file, stderr=subprocess.STDOUT)
                try:
                    dump = wait_for_injected_audio_dump(
                        process=process,
                        dump_dir=dump_dir,
                        audio_trace=audio_trace,
                        block_trace=block_trace,
                        text_byte_length=len(text.encode("utf-8")),
                        appliance_pcm_dump=appliance_pcm_dump if appliance_mode else None,
                        appliance_pcm_sample_rate=appliance_pcm_sample_rate,
                        deadline=time.monotonic() + self.timeout_seconds,
                    )
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

            dump = dump or select_injected_audio_dump(
                dump_dir=dump_dir,
                audio_trace=audio_trace,
                block_trace=block_trace,
                text_byte_length=len(text.encode("utf-8")),
            )
            if dump is not None:
                dump_path, sample_rate = dump
                pcm = postprocess_voice_pcm(dump_path.read_bytes(), sample_rate=sample_rate)
                pcm = apply_ltd_voice_params(pcm, sample_rate=sample_rate, voice=request.voice)
                return pcm_s16le_to_wav(pcm, sample_rate=sample_rate)

            if capture_mixed:
                injection_at = first_injection_time(block_trace, len(text.encode("utf-8")))
                output_pcm = select_injected_output_audio(
                    output_trace=output_trace,
                    injection_at=injection_at,
                    max_seconds=float(os.environ.get("TTSMODACHI_LTD_OUTPUT_CAPTURE_SECONDS", "4.5")),
                )
                if output_pcm is not None:
                    pcm, sample_rate = output_pcm
                    pcm = apply_ltd_voice_params(pcm, sample_rate=sample_rate, voice=request.voice)
                    return pcm_s16le_to_wav(pcm, sample_rate=sample_rate)

            if dump is None:
                raise RuntimeError(f"LTD render produced no PCM dumps after {round(time.monotonic() - started, 2)}s; see {log_path}")
        finally:
            if os.environ.get("TTSMODACHI_LTD_KEEP_RENDER_WORKDIR", "").lower() not in {"1", "true", "yes"}:
                shutil.rmtree(out_dir, ignore_errors=True)

    def start(self) -> None:
        if not self.warm_enabled or not self.prewarm_enabled:
            return
        self._validate_runtime_paths()
        self._ensure_governor()
        if ltd_prewarm_primer_enabled():
            if self._warm_prewarmer is not None and self._warm_prewarmer.is_alive():
                return
            self._warm_prewarm_started_at = time.monotonic()
            self._warm_prewarm_finished_at = None
            self._warm_prewarm_error = None
            self._warm_prewarmer = Thread(target=self._prewarm_primer, name="ltd-switch-prewarm", daemon=True)
            self._warm_prewarmer.start()
            if env_bool_default("TTSMODACHI_LTD_PREWARM_WAIT", False):
                self.wait_until_prewarmed(float(os.environ.get("TTSMODACHI_LTD_PREWARM_TIMEOUT_SECONDS", str(self.timeout_seconds))))
            return

        if self._warm_prewarmer is not None and self._warm_prewarmer.is_alive():
            return
        self._warm_prewarm_started_at = time.monotonic()
        self._warm_prewarm_finished_at = None
        self._warm_prewarm_error = None
        self._warm_prewarmer = Thread(target=self._prewarm_ready, name="ltd-switch-ready-prewarm", daemon=True)
        self._warm_prewarmer.start()
        if env_bool_default("TTSMODACHI_LTD_PREWARM_WAIT", False):
            self.wait_until_prewarmed(float(os.environ.get("TTSMODACHI_LTD_PREWARM_TIMEOUT_SECONDS", str(self.timeout_seconds))))

    def health(self) -> dict[str, object]:
        warm_alive = self._warm_process is not None and self._warm_process.poll() is None
        return {
            "engine": ENGINE_LTD_SWITCH,
            "target_build_id": self.target.main_build_id,
            "address_table": {
                "guest_base": self.addresses.guest_base,
                "request_addr": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_ADDR", self.addresses.request_addr),
                "request_text_prep_addr": self.addresses.request_text_prep_addr,
                "text_dispatcher_addr": self.addresses.text_dispatcher_addr,
                "capture_addrs": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CAPTURE_ADDRS", self.addresses.capture_addrs),
                "pcm_dump_addrs": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_DUMP_ADDRS", self.addresses.pcm_dump_addrs),
                "consumer_capture_addrs": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS", self.addresses.consumer_capture_addrs),
                "consumer_kick_addr": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR", self.addresses.consumer_kick_addr),
            },
            "ryubing_path": str(self.ryubing_path),
            "game_path": str(self.game_path),
            "data_dir": str(self.data_dir),
            "seed_data_dir": os.environ.get("TTSMODACHI_LTD_SEED_DATA_DIR", ""),
            "data_seeded": ltd_data_has_appliance_seed(self.data_dir),
            "work_dir": str(self.work_dir),
            "timeout_seconds": self.timeout_seconds,
            "memory_manager_mode": os.environ.get("TTSMODACHI_LTD_MEMORY_MANAGER_MODE", "HostMappedUnsafe"),
            "graphics_backend": os.environ.get("TTSMODACHI_LTD_GRAPHICS_BACKEND", ""),
            "capture_mode": os.environ.get("TTSMODACHI_LTD_CAPTURE_MODE", "voice-only"),
            "appliance_mode": env_bool_default("TTSMODACHI_LTD_APPLIANCE", True),
            "appliance_park": env_bool_default("TTSMODACHI_LTD_APPLIANCE_PARK", True),
            "appliance_host_park_sleep_ms": os.environ.get("TTSMODACHI_LTD_APPLIANCE_HOST_PARK_SLEEP_MS", "8"),
            "appliance_dispatch_on_capture": env_bool_default("TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE", True),
            "appliance_context_restore": env_bool_default("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESTORE", True),
            "appliance_park_on_capture_ready": env_bool_default("TTSMODACHI_LTD_APPLIANCE_PARK_ON_CAPTURE_READY", False),
            "appliance_trampoline_return_addr": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRAMPOLINE_RETURN_ADDR", "0x3004"),
            "appliance_context_resume_addr": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESUME_ADDR", "0"),
            "appliance_consumer_capture_addrs": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS", self.addresses.consumer_capture_addrs),
            "appliance_consumer_kick_addr": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR", self.addresses.consumer_kick_addr),
            "appliance_consumer_kick_max": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX", self.addresses.consumer_kick_max),
            "appliance_consumer_kick_after_dispatch_max": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX", "0"),
            "appliance_consumer_frame_file": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_FILE", ""),
            "appliance_memory_patch_file": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_FILE", ""),
            "appliance_context_trace_addrs": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ADDRS", ""),
            "appliance_context_dump_dir": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_DIR", ""),
            "dsp_trace": ltd_dsp_trace_enabled(env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)),
            "dummy_audio": env_bool_default("TTSMODACHI_LTD_DUMMY_AUDIO", env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)),
            "mute_device_sink": env_bool_default("TTSMODACHI_LTD_MUTE_DEVICE_SINK", env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)),
            "discard_present": env_bool_default("TTSMODACHI_LTD_DISCARD_PRESENT", env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)),
            "discard_present_after_prewarm": env_bool_default("TTSMODACHI_LTD_DISCARD_PRESENT_AFTER_PREWARM", False),
            "window_width": os.environ.get("TTSMODACHI_LTD_WINDOW_WIDTH", "320" if env_bool_default("TTSMODACHI_LTD_APPLIANCE", True) else ""),
            "window_height": os.environ.get("TTSMODACHI_LTD_WINDOW_HEIGHT", "180" if env_bool_default("TTSMODACHI_LTD_APPLIANCE", True) else ""),
            "low_dpi_window": env_bool_default("TTSMODACHI_LTD_LOW_DPI_WINDOW", env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)),
            "ready": (self.ryubing_path / "build" / "Ryujinx").exists() and self.game_path.is_file(),
            "warm_enabled": self.warm_enabled,
            "prewarm_enabled": self.prewarm_enabled,
            "warm_pid": self._warm_process.pid if warm_alive else None,
            "warm_ready": self.is_warm_ready(),
            "warm_paused": self._warm_paused,
            "warm_active_job_count": self._warm_active_job_count,
            "warm_idle_seconds": (
                round(max(0.0, time.monotonic() - self._warm_last_activity_at), 2)
                if warm_alive and self._warm_last_activity_at is not None
                else None
            ),
            "warm_resume_count": self._warm_resume_count,
            "warm_restart_count": self._warm_restart_count,
            "warm_last_recovery_reason": self._warm_last_recovery_reason,
            "warm_last_error": self._warm_last_error,
            "warm_no_present": self._warm_no_present_file is not None and self._warm_no_present_file.exists(),
            "warm_discard_present": self._warm_discard_present_file is not None and self._warm_discard_present_file.exists(),
            "warm_prewarming": self._warm_prewarmer is not None and self._warm_prewarmer.is_alive(),
            "warm_prewarm_done": self._warm_prewarm_finished_at is not None and self._warm_prewarm_error is None,
            "warm_prewarm_error": self._warm_prewarm_error,
            "warm_prewarm_primer": ltd_prewarm_primer_enabled(),
            "warm_prewarm_seconds": (
                round((self._warm_prewarm_finished_at or time.monotonic()) - self._warm_prewarm_started_at, 2)
                if self._warm_prewarm_started_at is not None
                else None
            ),
            "warm_age_seconds": round(time.monotonic() - self._warm_started_at, 2) if warm_alive and self._warm_started_at else None,
            "warm_dir": str(self._warm_dir) if self._warm_dir else None,
            "warm_last_render_ms": self._warm_last_render_ms,
            "warm_render_count": self._warm_render_count,
            "mode": ("warm" if self.warm_enabled else "cold")
            + ("-appliance-lightningjit-voice-only" if env_bool_default("TTSMODACHI_LTD_APPLIANCE", True) else "-ui-lightningjit-voice-only"),
        }

    def wait_until_warm_ready(self, timeout_seconds: float | None = None) -> bool:
        deadline = time.monotonic() + (timeout_seconds if timeout_seconds is not None else self.timeout_seconds)
        with self._warm_lock:
            if self._warm_process is None or self._warm_process.poll() is not None:
                max_text_bytes = int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96"))
                self._ensure_warm_process(max_text_bytes)
            return self._wait_until_warm_ready_locked(deadline=deadline)

    def wait_until_prewarmed(self, timeout_seconds: float | None = None) -> bool:
        deadline = time.monotonic() + (timeout_seconds if timeout_seconds is not None else self.timeout_seconds)
        while time.monotonic() < deadline:
            if self._warm_prewarm_finished_at is not None:
                return self._warm_prewarm_error is None
            if self._warm_prewarm_error is not None:
                return False
            if self.is_warm_ready():
                return True
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
        return False

    def is_warm_ready(self) -> bool:
        process = self._warm_process
        trace = self._warm_appliance_trace
        if process is None or process.poll() is not None or trace is None or not trace.exists():
            return False

        park_enabled = env_bool_default("TTSMODACHI_LTD_APPLIANCE_PARK", True)
        try:
            with trace.open(newline="") as file:
                for row in csv.DictReader(file):
                    event_reason = (row.get("event"), row.get("reason"))
                    if park_enabled:
                        if event_reason != ("park", "waiting-for-text"):
                            continue
                    elif event_reason != ("poll", "no-text"):
                        continue
                    request_object = row.get("request_object", "0x0")
                    voice_context = row.get("voice_context", "0x0")
                    if request_object not in {"", "0x0"} and voice_context not in {"", "0x0"}:
                        return True
        except OSError:
            return False
        return False

    def stop(self) -> None:
        self._warm_governor_stop.set()
        with self._warm_lock:
            self._stop_warm_process()

    def _render_warm(self, text: str, max_text_bytes: int, voice: VoiceParams) -> bytes:
        self._ensure_governor()
        self._ensure_warm_process(max_text_bytes)
        self._resume_warm_process()
        assert self._warm_process is not None
        assert self._warm_dump_dir is not None
        assert self._warm_text_file is not None
        assert self._warm_audio_trace is not None
        assert self._warm_block_trace is not None

        self._warm_active_job_count += 1
        render_started = time.perf_counter()
        self._warm_last_activity_at = time.monotonic()
        try:
            text_byte_length = len(text.encode("utf-8"))
            request_started = datetime.now(timezone.utc)
            size_snapshot = snapshot_dump_sizes(self._warm_dump_dir)
            appliance_mode = env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)
            appliance_pcm_start = (
                self._warm_appliance_pcm_dump.stat().st_size
                if appliance_mode and self._warm_appliance_pcm_dump is not None and self._warm_appliance_pcm_dump.exists()
                else 0
            )
            atomic_write_text(self._warm_text_file, text)

            if appliance_mode and self._warm_appliance_pcm_dump is not None:
                assert self._warm_appliance_trace is not None
                dispatch_at = wait_for_warm_appliance_dispatch(
                    process=self._warm_process,
                    appliance_trace=self._warm_appliance_trace,
                    text_byte_length=text_byte_length,
                    after=request_started,
                    deadline=time.monotonic() + self.timeout_seconds,
                )
                if dispatch_at is None:
                    self._restart_warm_process("LTD warm render timed out waiting for appliance dispatch")
                    raise RuntimeError(f"LTD warm render timed out waiting for appliance dispatch; see {self._warm_log_path}")

                sample_rate = self._warm_appliance_pcm_sample_rate
                pcm = wait_for_warm_pcm_delta(
                    process=self._warm_process,
                    pcm_dump=self._warm_appliance_pcm_dump,
                    start_size=appliance_pcm_start,
                    text_byte_length=text_byte_length,
                    sample_rate=sample_rate,
                    deadline=time.monotonic() + self.timeout_seconds,
                )
                if self._warm_appliance_pcm_ack_file is not None:
                    atomic_write_text(self._warm_appliance_pcm_ack_file, str(time.time_ns()))
            else:
                injection_at = wait_for_warm_injection(
                    process=self._warm_process,
                    block_trace=self._warm_block_trace,
                    text_byte_length=text_byte_length,
                    after=request_started,
                    deadline=time.monotonic() + self.timeout_seconds,
                )
                if injection_at is None:
                    self._restart_warm_process("LTD warm render timed out waiting for text injection")
                    raise RuntimeError(f"LTD warm render timed out waiting for text injection; see {self._warm_log_path}")

                pcm, sample_rate = wait_for_warm_audio_delta(
                    process=self._warm_process,
                    dump_dir=self._warm_dump_dir,
                    audio_trace=self._warm_audio_trace,
                    injection_at=injection_at,
                    text_byte_length=text_byte_length,
                    size_snapshot=size_snapshot,
                    deadline=time.monotonic() + self.timeout_seconds,
                )
            self._warm_last_render_ms = round((time.perf_counter() - render_started) * 1000, 2)
            self._warm_render_count += 1
            self._warm_last_error = None
            pcm = postprocess_voice_pcm(pcm, sample_rate=sample_rate)
            pcm = apply_ltd_voice_params(pcm, sample_rate=sample_rate, voice=voice)
            return pcm_s16le_to_wav(pcm, sample_rate=sample_rate)
        except Exception as exc:
            self._warm_last_error = str(exc)
            raise
        finally:
            self._warm_active_job_count = max(0, self._warm_active_job_count - 1)
            self._warm_last_activity_at = time.monotonic()

    def _prewarm_primer(self) -> None:
        text = os.environ.get("TTSMODACHI_LTD_PREWARM_TEXT", "TTSmodachi ready.").replace("\n", " ").strip()
        if not text:
            text = "TTSmodachi ready."

        try:
            with self._warm_lock:
                self._render_warm(text, int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96")), VoiceParams(engine=ENGINE_LTD_SWITCH))
                self._enable_no_present_after_prewarm()
                self._enable_discard_present_after_prewarm()
            self._warm_prewarm_finished_at = time.monotonic()
        except Exception as exc:
            self._warm_prewarm_error = str(exc)
            with self._warm_lock:
                self._stop_warm_process()

    def _prewarm_ready(self) -> None:
        try:
            with self._warm_lock:
                self._ensure_warm_process(int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96")))
                deadline = time.monotonic() + float(os.environ.get("TTSMODACHI_LTD_PREWARM_TIMEOUT_SECONDS", str(self.timeout_seconds)))
                if not self._wait_until_warm_ready_locked(deadline=deadline):
                    raise RuntimeError(f"LTD warm appliance did not reach VoiceText ready state; see {self._warm_log_path}")
                self._warm_last_activity_at = time.monotonic()
            self._warm_prewarm_finished_at = time.monotonic()
        except Exception as exc:
            self._warm_prewarm_error = str(exc)
            with self._warm_lock:
                self._stop_warm_process()

    def _ensure_warm_process(self, max_text_bytes: int) -> None:
        if self._warm_process is not None and self._warm_process.poll() is None:
            return

        self._stop_warm_process()
        self._warm_dir = self.work_dir / f"warm-{uuid.uuid4().hex}"
        self._warm_dump_dir = self._warm_dir / "audio-dumps"
        self._warm_text_file = self._warm_dir / "text.txt"
        self._warm_audio_trace = self._warm_dir / "audio.csv"
        self._warm_block_trace = self._warm_dir / "block-trace.csv"
        self._warm_appliance_trace = self._warm_dir / "appliance.csv"
        self._warm_appliance_pcm_dump = self._warm_dir / "appliance.pcm"
        self._warm_appliance_pcm_ack_file = self._warm_dir / "appliance-pcm-ack.txt"
        self._warm_no_present_file = self._warm_dir / "no-present"
        self._warm_discard_present_file = self._warm_dir / "discard-present"
        self._warm_appliance_pcm_sample_rate = int(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_SAMPLE_RATE", "32000"))
        self._warm_log_path = self._warm_dir / "ryubing.log"
        self._warm_dump_dir.mkdir(parents=True, exist_ok=True)
        self._warm_text_file.write_text("")

        appliance_mode = env_bool_default("TTSMODACHI_LTD_APPLIANCE", True)
        dsp_trace_enabled = ltd_dsp_trace_enabled(appliance_mode)
        touch_file = self._warm_dir / "touch.txt"
        input_file = self._warm_dir / "input.txt"
        env = os.environ.copy()
        env.update(
            {
                "DOTNET_ROOT": self.dotnet_root,
                "RYUJINX_HEADLESS_SWKBD_AUTO_ACCEPT": "true",
                "RYUJINX_HEADLESS_SWKBD_TEXTS": "Cole|TTSmodachi|Ryujinx|Tomodachi",
                "RYUJINX_TTSMODACHI_DISABLE_HYPERVISOR": "true",
                "RYUJINX_TTSMODACHI_DUMMY_AUDIO": ltd_dummy_audio_value(appliance_mode),
                "RYUJINX_TTSMODACHI_MUTE_DEVICE_SINK": ltd_mute_device_sink_value(appliance_mode),
                "RYUJINX_TTSMODACHI_NO_PRESENT": os.environ.get("TTSMODACHI_LTD_NO_PRESENT", "false"),
                "RYUJINX_TTSMODACHI_NO_PRESENT_FILE": str(self._warm_no_present_file),
                "RYUJINX_TTSMODACHI_DISCARD_PRESENT": os.environ.get("TTSMODACHI_LTD_DISCARD_PRESENT", "true" if appliance_mode else "false"),
                "RYUJINX_TTSMODACHI_DISCARD_PRESENT_FILE": str(self._warm_discard_present_file),
                "RYUJINX_TTSMODACHI_WINDOW_WIDTH": os.environ.get("TTSMODACHI_LTD_WINDOW_WIDTH", "320" if appliance_mode else ""),
                "RYUJINX_TTSMODACHI_WINDOW_HEIGHT": os.environ.get("TTSMODACHI_LTD_WINDOW_HEIGHT", "180" if appliance_mode else ""),
                "RYUJINX_TTSMODACHI_LOW_DPI_WINDOW": os.environ.get("TTSMODACHI_LTD_LOW_DPI_WINDOW", "true" if appliance_mode else "false"),
                "RYUJINX_TTSMODACHI_GUEST_TRACE_BASE": self.addresses.guest_base,
                "RYUJINX_TTSMODACHI_BLOCK_TRACE": str(self._warm_block_trace),
                "RYUJINX_TTSMODACHI_BLOCK_TRACE_MAX_EVENTS": "10000",
                "RYUJINX_TTSMODACHI_MEMORY_WRITE_TRACE": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_TRACE", ""),
                "RYUJINX_TTSMODACHI_MEMORY_WRITE_RANGES": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_RANGES", ""),
                "RYUJINX_TTSMODACHI_MEMORY_WRITE_MAX_EVENTS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_MAX_EVENTS", "20000"),
                "RYUJINX_TTSMODACHI_MEMORY_WRITE_START_SECONDS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_START_SECONDS", ""),
                "RYUJINX_TTSMODACHI_MEMORY_WRITE_DURATION_SECONDS": os.environ.get("TTSMODACHI_LTD_MEMORY_WRITE_DURATION_SECONDS", ""),
            }
        )
        if dsp_trace_enabled:
            env.update(
                {
                    "RYUJINX_TTSMODACHI_AUDIO_TRACE": str(self._warm_audio_trace),
                    "RYUJINX_TTSMODACHI_AUDIO_TRACE_FORMATS": "PcmInt16,PcmFloat",
                    "RYUJINX_TTSMODACHI_AUDIO_TRACE_MIN_PEAK": "0.001",
                    "RYUJINX_TTSMODACHI_AUDIO_TRACE_MAX_EVENTS": "100000",
                    "RYUJINX_TTSMODACHI_AUDIO_DUMP_DIR": str(self._warm_dump_dir),
                    "RYUJINX_TTSMODACHI_AUDIO_DUMP_MAX_SECONDS": os.environ.get("TTSMODACHI_LTD_WARM_DUMP_MAX_SECONDS", "120"),
                }
            )
        if ltd_boot_input_enabled(appliance_mode):
            env.update(
                {
                    "RYUJINX_TTSMODACHI_AUTO_A": "true",
                    "RYUJINX_TTSMODACHI_AUTO_A_START_FRAME": os.environ.get("TTSMODACHI_LTD_AUTO_A_START_FRAME", "300"),
                    "RYUJINX_TTSMODACHI_AUTO_A_INTERVAL_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_INTERVAL_FRAMES", "60"),
                    "RYUJINX_TTSMODACHI_AUTO_A_DURATION_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_DURATION_FRAMES", "6"),
                    "RYUJINX_TTSMODACHI_TOUCH_SCRIPT": os.environ.get("TTSMODACHI_LTD_TOUCH_SCRIPT", build_touch_script()),
                    "RYUJINX_TTSMODACHI_TOUCH_FILE": str(touch_file),
                    "RYUJINX_TTSMODACHI_INPUT_FILE": str(input_file),
                }
            )
            touch_file.write_text("")
            input_file.write_text("")

        if appliance_mode:
            env.update(
                {
                    "RYUJINX_TTSMODACHI_APPLIANCE": "true",
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_FILE": str(self._warm_text_file),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_MAX_BYTES": str(max_text_bytes),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRACE": str(self._warm_appliance_trace),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_MAX_EVENTS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_MAX_EVENTS", "100000"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_POLLS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_POLLS", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_CONSUMER_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_CONSUMER_REGISTERS", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRACE_REQUEST_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRACE_REQUEST_REGISTERS", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_TRACE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ADDRS", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_TRACE_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ONCE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_DIR", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_BYTES", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_DUMP_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_REGISTERS", "0,1,2,3,19,20,21,22,23,24,29,30,31"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_DIR", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_BYTES", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_DUMP_REGISTERS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_REGISTERS", "0,19,21,22"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_FILE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_FILE", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_LOAD": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_LOAD", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_FRAME_SAVE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_SAVE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_MEMORY_PATCH_FILE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_FILE", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_MEMORY_PATCH_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_ONCE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_DIR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_DIR", ""),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_BYTES", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_DUMP_ONCE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_ONCE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_INTERVAL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_INTERVAL_MS", "1200"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_REPEATS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_REPEATS", "1"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_ON_CAPTURE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_RESTORE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESTORE", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PARK_ON_CAPTURE_READY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_ON_CAPTURE_READY", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_CONTEXT_CAPTURE": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_CONTEXT_CAPTURE", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_CONTEXT_REPLAY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_CONTEXT_REPLAY", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_DISPATCH_CONTEXT_REPLAY": os.environ.get("TTSMODACHI_LTD_APPLIANCE_DISPATCH_CONTEXT_REPLAY", "false"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TRAMPOLINE_RETURN_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TRAMPOLINE_RETURN_ADDR", "0x3004"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONTEXT_RESUME_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESUME_ADDR", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_CAPTURE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS", self.addresses.consumer_capture_addrs),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR", self.addresses.consumer_kick_addr),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_MAX": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX", self.addresses.consumer_kick_max),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_INTERVAL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_INTERVAL_MS", self.addresses.consumer_kick_interval_ms),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PARK": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK", "true"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PARK_POLL_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_POLL_MS", "25"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PARK_MAX_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PARK_MAX_MS", "0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_HOST_PARK_SLEEP_MS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_HOST_PARK_SLEEP_MS", "8"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_ADDR", self.addresses.request_addr),
                    "RYUJINX_TTSMODACHI_APPLIANCE_CAPTURE_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_CAPTURE_ADDRS", self.addresses.capture_addrs),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP_ADDRS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_DUMP_ADDRS", self.addresses.pcm_dump_addrs),
                    "RYUJINX_TTSMODACHI_APPLIANCE_MANAGER_GLOBAL_ADDR": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MANAGER_GLOBAL_ADDR", self.addresses.manager_global_addr),
                    "RYUJINX_TTSMODACHI_APPLIANCE_MANAGER_INNER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_MANAGER_INNER_OFFSET", self.addresses.manager_inner_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_REQUEST_OBJECT_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_REQUEST_OBJECT_OFFSET", self.addresses.request_object_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_BUFFER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_BUFFER_OFFSET", self.addresses.text_buffer_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_POINTER_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_POINTER_OFFSET", self.addresses.text_pointer_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_TEXT_LENGTH_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_TEXT_LENGTH_OFFSET", self.addresses.text_length_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_READY_FLAG_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_READY_FLAG_OFFSET", self.addresses.ready_flag_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_ALT_TEXT_FLAG_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_ALT_TEXT_FLAG_OFFSET", self.addresses.alternate_text_flag_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_VOICE_CONTEXT_OFFSET": os.environ.get("TTSMODACHI_LTD_APPLIANCE_VOICE_CONTEXT_OFFSET", self.addresses.voice_context_offset),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP": str(self._warm_appliance_pcm_dump),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_ACK_FILE": str(self._warm_appliance_pcm_ack_file),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_DUMP_MAX_BYTES": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_TOTAL_MAX_BYTES", str(64 * 1024 * 1024)),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_SAMPLE_RATE": str(self._warm_appliance_pcm_sample_rate),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_MIN_SECONDS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MIN_SECONDS", "1.0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_MAX_SECONDS": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MAX_SECONDS", "5.0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_TEXT_BYTES_PER_SECOND": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_TEXT_BYTES_PER_SECOND", "14.0"),
                    "RYUJINX_TTSMODACHI_APPLIANCE_PCM_CAPTURE_TEXT_BYTES_PER_SECOND": os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_CAPTURE_TEXT_BYTES_PER_SECOND", "14.0"),
                    "RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS": os.environ.get(
                        "TTSMODACHI_LTD_APPLIANCE_BLOCK_TRACE_ADDRS",
                        "",
                    ),
                }
            )
        else:
            env.update(
                {
                    "RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS": self.addresses.request_text_prep_addr,
                    "RYUJINX_TTSMODACHI_AUTO_A": "true",
                    "RYUJINX_TTSMODACHI_AUTO_A_START_FRAME": os.environ.get("TTSMODACHI_LTD_AUTO_A_START_FRAME", "300"),
                    "RYUJINX_TTSMODACHI_AUTO_A_INTERVAL_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_INTERVAL_FRAMES", "60"),
                    "RYUJINX_TTSMODACHI_AUTO_A_DURATION_FRAMES": os.environ.get("TTSMODACHI_LTD_AUTO_A_DURATION_FRAMES", "6"),
                    "RYUJINX_TTSMODACHI_TOUCH_SCRIPT": build_touch_script(),
                    "RYUJINX_TTSMODACHI_TOUCH_FILE": str(touch_file),
                    "RYUJINX_TTSMODACHI_INPUT_FILE": str(input_file),
                    "RYUJINX_TTSMODACHI_TEXT_INJECT_FILE": str(self._warm_text_file),
                    "RYUJINX_TTSMODACHI_TEXT_INJECT_ADDR": os.environ.get("RYUJINX_TTSMODACHI_TEXT_INJECT_ADDR", self.addresses.request_text_prep_addr),
                    "RYUJINX_TTSMODACHI_TEXT_INJECT_MAX_BYTES": str(max_text_bytes),
                }
            )
            touch_file.write_text("")
            input_file.write_text("")
        command = [
            "./build/Ryujinx",
            "--no-gui",
            "--root-data-dir",
            str(self.data_dir),
            "--disable-file-logging",
            "--ignore-missing-services",
            "--skip-user-profiles-manager",
            "--system-language",
            "AmericanEnglish",
            "--system-region",
            "USA",
            "--use-hypervisor",
            "false",
            "--memory-manager-mode",
            os.environ.get("TTSMODACHI_LTD_MEMORY_MANAGER_MODE", "HostMappedUnsafe"),
            str(self.game_path),
        ]
        if env_bool_default("TTSMODACHI_LTD_DISABLE_SHADER_CACHE", appliance_mode):
            command.insert(-1, "--disable-shader-cache")
        apply_ltd_command_tuning(command)
        if env_bool("TTSMODACHI_LTD_DISABLE_PTC"):
            command.insert(-1, "--disable-ptc")
        if env_bool("TTSMODACHI_LTD_DEBUG_LOGS"):
            command.insert(-1, "--enable-debug-logs")

        self._warm_log_file = self._warm_log_path.open("wb")
        self._warm_process = subprocess.Popen(command, cwd=self.ryubing_path, env=env, stdout=self._warm_log_file, stderr=subprocess.STDOUT)
        self._warm_started_at = time.monotonic()
        self._warm_last_activity_at = self._warm_started_at
        self._warm_paused = False

    def _enable_no_present_after_prewarm(self) -> None:
        if not env_bool_default("TTSMODACHI_LTD_NO_PRESENT_AFTER_PREWARM", False):
            return
        if self._warm_no_present_file is None:
            return
        self._warm_no_present_file.write_text("1")

    def _enable_discard_present_after_prewarm(self) -> None:
        if not env_bool_default("TTSMODACHI_LTD_DISCARD_PRESENT_AFTER_PREWARM", False):
            return
        if self._warm_discard_present_file is None:
            return
        self._warm_discard_present_file.write_text("1")

    def _stop_warm_process(self) -> None:
        process = self._warm_process
        self._warm_process = None
        if process is not None and process.poll() is None:
            if self._warm_paused:
                try:
                    os.kill(process.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self._warm_log_file is not None:
            self._warm_log_file.close()
            self._warm_log_file = None
        self._warm_started_at = None
        self._warm_last_activity_at = None
        self._warm_paused = False
        self._warm_discard_present_file = None
        self._warm_appliance_pcm_ack_file = None

    def _restart_warm_process(self, reason: str) -> None:
        self._warm_restart_count += 1
        self._warm_last_recovery_reason = reason
        self._warm_last_error = reason
        self._stop_warm_process()
        self._ensure_warm_process(int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96")))

    def _resume_warm_process(self) -> None:
        process = self._warm_process
        if process is None:
            self._ensure_warm_process(int(os.environ.get("TTSMODACHI_LTD_TEXT_MAX_BYTES", "96")))
            process = self._warm_process
        if process is None:
            raise RuntimeError("LTD warm process did not start")
        if process.poll() is not None:
            self._restart_warm_process(f"LTD warm process exited with code {process.returncode}")
            return
        if not self._warm_paused:
            return
        try:
            os.kill(process.pid, signal.SIGCONT)
        except ProcessLookupError:
            self._warm_paused = False
            self._restart_warm_process("LTD warm process disappeared while paused")
            return
        self._warm_paused = False
        self._warm_resume_count += 1
        self._warm_last_activity_at = time.monotonic()
        time.sleep(min(self._warm_idle_resume_timeout, 0.1))
        if process.poll() is not None:
            self._restart_warm_process(f"LTD warm process exited with code {process.returncode} after resume")

    def _ensure_governor(self) -> None:
        if not self.warm_enabled or self._warm_governor_stop.is_set():
            return
        if self._warm_governor is not None and self._warm_governor.is_alive():
            return
        self._warm_governor = Thread(target=self._govern_warm_process, name="ltd-switch-idle-governor", daemon=True)
        self._warm_governor.start()

    def _govern_warm_process(self) -> None:
        poll_seconds = float(os.environ.get("TTSMODACHI_LTD_IDLE_POLL_SECONDS", "0.25"))
        while not self._warm_governor_stop.wait(poll_seconds):
            with self._warm_lock:
                self._maybe_suspend_warm_process()

    def _maybe_suspend_warm_process(self) -> None:
        if self._warm_idle_suspend_seconds <= 0 or self._warm_active_job_count > 0 or self._warm_paused:
            return
        process = self._warm_process
        if process is None:
            return
        if process.poll() is not None:
            self._restart_warm_process(f"LTD warm process exited with code {process.returncode} while idle")
            return
        if self._warm_last_activity_at is None or time.monotonic() - self._warm_last_activity_at < self._warm_idle_suspend_seconds:
            return
        if self._warm_prewarm_finished_at is None or not self.is_warm_ready():
            return
        try:
            os.kill(process.pid, signal.SIGSTOP)
        except ProcessLookupError:
            return
        self._warm_paused = True

    def _wait_until_warm_ready_locked(self, *, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if self._warm_process is None or self._warm_process.poll() is not None:
                return False
            if self.is_warm_ready():
                return True
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
        return False

    def _validate_runtime_paths(self) -> None:
        if not self.game_path.is_file():
            raise FileNotFoundError(f"LTD game file not found: {self.game_path}")
        if not (self.ryubing_path / "build" / "Ryujinx").exists():
            raise FileNotFoundError(f"Ryubing build not found: {self.ryubing_path / 'build' / 'Ryujinx'}")
        self._bootstrap_data_dir()

    def _bootstrap_data_dir(self) -> None:
        seed = os.environ.get("TTSMODACHI_LTD_SEED_DATA_DIR", "").strip()
        if not seed or ltd_data_has_appliance_seed(self.data_dir):
            return

        seed_dir = Path(seed).expanduser().resolve()
        if seed_dir == self.data_dir:
            return
        if not seed_dir.is_dir():
            raise FileNotFoundError(f"LTD seed data dir not found: {seed_dir}")
        if not ltd_data_has_appliance_seed(seed_dir):
            raise FileNotFoundError(f"LTD seed data dir does not contain required save/profile data: {seed_dir}")

        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seed_dir, self.data_dir, dirs_exist_ok=True)


def build_touch_script() -> str:
    events: list[str] = []
    primary_start = int(os.environ.get("TTSMODACHI_LTD_TOUCH_PRIMARY_START_FRAME", "360"))
    primary_stop = int(os.environ.get("TTSMODACHI_LTD_TOUCH_PRIMARY_STOP_FRAME", "36000"))
    primary_step = int(os.environ.get("TTSMODACHI_LTD_TOUCH_PRIMARY_STEP_FRAMES", "180"))
    secondary_start = int(os.environ.get("TTSMODACHI_LTD_TOUCH_SECONDARY_START_FRAME", "12000"))
    secondary_stop = int(os.environ.get("TTSMODACHI_LTD_TOUCH_SECONDARY_STOP_FRAME", "60000"))
    secondary_step = int(os.environ.get("TTSMODACHI_LTD_TOUCH_SECONDARY_STEP_FRAMES", "240"))
    for frame in range(primary_start, primary_stop, primary_step):
        events.append(f"{frame}:700:610:35")
    for frame in range(secondary_start, secondary_stop, secondary_step):
        events.append(f"{frame}:1110:75:35")
    return ";".join(events)


def apply_ltd_command_tuning(command: list[str]) -> None:
    if env_bool_default("TTSMODACHI_LTD_QUIET_LOGS", True):
        for flag in ("--disable-stub-logs", "--disable-info-logs", "--disable-guest-logs"):
            command.insert(-1, flag)

    resolution_scale = os.environ.get("TTSMODACHI_LTD_RESOLUTION_SCALE", "").strip()
    if resolution_scale:
        command.insert(-1, "--resolution-scale")
        command.insert(-1, resolution_scale)

    backend_threading = os.environ.get("TTSMODACHI_LTD_BACKEND_THREADING", "").strip()
    if backend_threading:
        command.insert(-1, "--backend-threading")
        command.insert(-1, backend_threading)

    graphics_backend = os.environ.get("TTSMODACHI_LTD_GRAPHICS_BACKEND", "").strip()
    if graphics_backend:
        command.insert(-1, "--graphics-backend")
        command.insert(-1, graphics_backend)


def select_injected_audio_dump(
    *,
    dump_dir: Path,
    audio_trace: Path,
    block_trace: Path,
    text_byte_length: int,
) -> tuple[Path, int] | None:
    injection_at = first_injection_time(block_trace, text_byte_length)
    if injection_at is None:
        return None

    if not audio_trace.exists():
        return None

    first_seen_by_command: dict[str, tuple[datetime, int]] = {}
    with audio_trace.open(newline="") as file:
        for row in csv.reader(file):
            if len(row) < 6:
                continue
            timestamp = parse_trace_time(row[0])
            if timestamp is None or timestamp < injection_at:
                continue
            command_id = row[3]
            try:
                sample_rate = int(row[5])
            except ValueError:
                sample_rate = 48000
            first_seen_by_command.setdefault(command_id, (timestamp, sample_rate))

    candidates: list[tuple[int, datetime, Path, int]] = []
    for command_id, (first_seen_at, sample_rate) in first_seen_by_command.items():
        matches = sorted(dump_dir.glob(f"*-{command_id}-*.s16le"), key=lambda path: path.stat().st_size, reverse=True)
        if matches:
            candidates.append((matches[0].stat().st_size, first_seen_at, matches[0], sample_rate))
    if not candidates:
        return None

    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    _, _, path, sample_rate = candidates[0]
    return path, sample_rate


def wait_for_injected_audio_dump(
    *,
    process: subprocess.Popen[bytes],
    dump_dir: Path,
    audio_trace: Path,
    block_trace: Path,
    text_byte_length: int,
    appliance_pcm_dump: Path | None = None,
    appliance_pcm_sample_rate: int = 32000,
    deadline: float,
) -> tuple[Path, int] | None:
    selected: tuple[Path, int] | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break

        if appliance_pcm_dump is not None and pcm_dump_ready(appliance_pcm_dump, appliance_pcm_sample_rate):
            return appliance_pcm_dump, appliance_pcm_sample_rate

        selected = select_injected_audio_dump(
            dump_dir=dump_dir,
            audio_trace=audio_trace,
            block_trace=block_trace,
            text_byte_length=text_byte_length,
        )
        if selected is not None and pcm_dump_ready(selected[0], selected[1]):
            return selected

        time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
    return selected if selected is not None and pcm_dump_ready(selected[0], selected[1], require_stable=False) else None


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def snapshot_dump_sizes(dump_dir: Path) -> dict[Path, int]:
    return {path: path.stat().st_size for path in dump_dir.glob("*.s16le")}


def wait_for_warm_injection(
    *,
    process: subprocess.Popen[bytes],
    block_trace: Path,
    text_byte_length: int,
    after: datetime,
    deadline: float,
) -> datetime | None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        injection_at = latest_injection_time(block_trace, text_byte_length, after)
        if injection_at is not None:
            return injection_at
        time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
    return None


def wait_for_warm_appliance_dispatch(
    *,
    process: subprocess.Popen[bytes],
    appliance_trace: Path,
    text_byte_length: int,
    after: datetime,
    deadline: float,
) -> datetime | None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        dispatch_at = latest_appliance_dispatch_time(appliance_trace, text_byte_length, after)
        if dispatch_at is not None:
            return dispatch_at
        time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
    return None


def latest_appliance_dispatch_time(appliance_trace: Path, text_byte_length: int, after: datetime) -> datetime | None:
    if not appliance_trace.exists():
        return None

    latest: datetime | None = None
    with appliance_trace.open(newline="") as file:
        for row in csv.DictReader(file):
            if row.get("event") != "dispatch":
                continue
            timestamp = parse_trace_time(row.get("utc", ""))
            if timestamp is None or timestamp < after:
                continue
            try:
                length = int(row.get("text_length", "0"))
            except ValueError:
                continue
            if length == text_byte_length:
                latest = timestamp
    return latest


def latest_injection_time(block_trace: Path, text_byte_length: int, after: datetime) -> datetime | None:
    if not block_trace.exists():
        return None

    latest: datetime | None = None
    with block_trace.open(newline="") as file:
        for row in csv.DictReader(file):
            if row.get("relative_address") != "0x444660":
                continue
            timestamp = parse_trace_time(row.get("utc", ""))
            if timestamp is None or timestamp < after:
                continue
            try:
                length = int(row.get("x3", "0"), 16)
            except ValueError:
                continue
            if length == text_byte_length:
                latest = timestamp
    return latest


def wait_for_warm_audio_delta(
    *,
    process: subprocess.Popen[bytes],
    dump_dir: Path,
    audio_trace: Path,
    injection_at: datetime,
    text_byte_length: int,
    size_snapshot: dict[Path, int],
    deadline: float,
) -> tuple[bytes, int]:
    selected_path: Path | None = None
    selected_sample_rate = 48000
    stable_since: float | None = None
    last_size = -1
    min_seconds = max(0.18, min(0.55, text_byte_length / 80.0))

    while time.monotonic() < deadline:
        if process.poll() is not None:
            break

        candidate = select_audio_candidate_after(audio_trace=audio_trace, dump_dir=dump_dir, injection_at=injection_at)
        if candidate is None:
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
            continue

        path, sample_rate = candidate
        start = size_snapshot.get(path, 0)
        size = path.stat().st_size
        if size <= start + int(sample_rate * 2 * min_seconds):
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
            continue

        if selected_path != path or size != last_size:
            selected_path = path
            selected_sample_rate = sample_rate
            last_size = size
            stable_since = time.monotonic()
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
            continue

        stable_seconds = float(os.environ.get("TTSMODACHI_LTD_VOICE_STABLE_SECONDS", "0.75"))
        if stable_since is not None and time.monotonic() - stable_since >= stable_seconds:
            with path.open("rb") as file:
                file.seek(start)
                return file.read(size - start), selected_sample_rate

        time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))

    raise RuntimeError("LTD warm render timed out waiting for audio after text injection")


def wait_for_warm_pcm_delta(
    *,
    process: subprocess.Popen[bytes],
    pcm_dump: Path,
    start_size: int,
    text_byte_length: int,
    sample_rate: int,
    deadline: float,
) -> bytes:
    expected_bytes = estimate_appliance_pcm_bytes(text_byte_length, sample_rate)
    wait_for_quiet_tail = env_bool_default("TTSMODACHI_LTD_PCM_WAIT_FOR_QUIET_TAIL", False)
    budget_bytes = estimate_appliance_pcm_capture_budget_bytes(text_byte_length, sample_rate) if wait_for_quiet_tail else expected_bytes
    min_bytes = int(sample_rate * 2 * float(os.environ.get("TTSMODACHI_LTD_MIN_VOICE_SECONDS", "0.35")))
    end_silence_seconds = float(os.environ.get("TTSMODACHI_LTD_PCM_END_SILENCE_SECONDS", "0.45"))
    end_threshold = int(os.environ.get("TTSMODACHI_LTD_PCM_END_SILENCE_THRESHOLD", "128"))
    end_pad_seconds = float(os.environ.get("TTSMODACHI_LTD_PCM_END_PAD_SECONDS", "0.04"))
    stable_since: float | None = None
    last_size = -1

    while time.monotonic() < deadline:
        if process.poll() is not None:
            break

        if not pcm_dump.exists():
            time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))
            continue

        size = pcm_dump.stat().st_size
        delta = size - start_size
        if not wait_for_quiet_tail and delta >= expected_bytes:
            with pcm_dump.open("rb") as file:
                file.seek(start_size)
                return file.read(expected_bytes)

        if delta >= min_bytes:
            with pcm_dump.open("rb") as file:
                file.seek(start_size)
                pcm = file.read(min(delta, budget_bytes))

            if wait_for_quiet_tail:
                quiet_cutoff = pcm_quiet_tail_cutoff(
                    pcm,
                    sample_rate=sample_rate,
                    threshold=end_threshold,
                    tail_seconds=end_silence_seconds,
                    pad_seconds=end_pad_seconds,
                )
                if quiet_cutoff is not None:
                    return pcm[:quiet_cutoff]

            if size != last_size:
                last_size = size
                stable_since = time.monotonic()
            elif stable_since is not None and time.monotonic() - stable_since >= float(os.environ.get("TTSMODACHI_LTD_VOICE_STABLE_SECONDS", "0.75")):
                return pcm

        time.sleep(float(os.environ.get("TTSMODACHI_LTD_RENDER_POLL_SECONDS", "0.15")))

    raise RuntimeError("LTD warm render timed out waiting for appliance PCM after text injection")


def estimate_appliance_pcm_bytes(text_byte_length: int, sample_rate: int) -> int:
    return estimate_appliance_pcm_duration_bytes(
        text_byte_length,
        sample_rate,
        bytes_per_second_env="TTSMODACHI_LTD_APPLIANCE_PCM_TEXT_BYTES_PER_SECOND",
        bytes_per_second_default="14.0",
    )


def estimate_appliance_pcm_capture_budget_bytes(text_byte_length: int, sample_rate: int) -> int:
    return estimate_appliance_pcm_duration_bytes(
        text_byte_length,
        sample_rate,
        bytes_per_second_env="TTSMODACHI_LTD_APPLIANCE_PCM_CAPTURE_TEXT_BYTES_PER_SECOND",
        bytes_per_second_default="10.0",
    )


def estimate_appliance_pcm_duration_bytes(
    text_byte_length: int,
    sample_rate: int,
    *,
    bytes_per_second_env: str,
    bytes_per_second_default: str,
) -> int:
    min_seconds = max(0.1, float(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MIN_SECONDS", "1.0")))
    max_seconds = max(min_seconds, float(os.environ.get("TTSMODACHI_LTD_APPLIANCE_PCM_MAX_SECONDS", "5.0")))
    bytes_per_second = max(1.0, float(os.environ.get(bytes_per_second_env, bytes_per_second_default)))
    seconds = min(max_seconds, max(min_seconds, text_byte_length / bytes_per_second))
    byte_count = math.ceil(sample_rate * 2 * seconds)
    return byte_count if byte_count % 2 == 0 else byte_count + 1


def pcm_quiet_tail_cutoff(
    pcm: bytes,
    *,
    sample_rate: int,
    threshold: int,
    tail_seconds: float,
    pad_seconds: float,
) -> int | None:
    if len(pcm) < 2:
        return None
    if len(pcm) % 2:
        pcm = pcm[:-1]

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    last_loud_sample: int | None = None
    for index in range(len(samples) - 1, -1, -1):
        if abs(samples[index]) >= threshold:
            last_loud_sample = index
            break
    if last_loud_sample is None:
        return None

    quiet_samples = len(samples) - last_loud_sample - 1
    if quiet_samples < int(sample_rate * tail_seconds):
        return None

    pad_samples = int(sample_rate * pad_seconds)
    cutoff_samples = min(len(samples), last_loud_sample + 1 + pad_samples)
    return cutoff_samples * 2


def select_audio_candidate_after(
    *,
    audio_trace: Path,
    dump_dir: Path,
    injection_at: datetime,
) -> tuple[Path, int] | None:
    if not audio_trace.exists():
        return None

    candidates: list[tuple[int, datetime, Path, int]] = []
    with audio_trace.open(newline="") as file:
        for row in csv.reader(file):
            if len(row) < 6:
                continue
            timestamp = parse_trace_time(row[0])
            if timestamp is None or timestamp < injection_at:
                continue
            command_id = row[3]
            try:
                sample_rate = int(row[5])
            except ValueError:
                sample_rate = 48000
            matches = sorted(dump_dir.glob(f"*-{command_id}-*.s16le"), key=lambda path: path.stat().st_size, reverse=True)
            for path in matches:
                candidates.append((path.stat().st_size, timestamp, path, sample_rate))

    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    _, _, path, sample_rate = candidates[0]
    return path, sample_rate


def pcm_dump_ready(path: Path, sample_rate: int, *, require_stable: bool = True) -> bool:
    if not path.is_file():
        return False

    stat = path.stat()
    min_seconds = float(os.environ.get("TTSMODACHI_LTD_MIN_VOICE_SECONDS", "0.35"))
    if stat.st_size < int(sample_rate * 2 * min_seconds):
        return False

    if not require_stable:
        return True

    stable_seconds = float(os.environ.get("TTSMODACHI_LTD_VOICE_STABLE_SECONDS", "0.75"))
    return time.time() - stat.st_mtime >= stable_seconds


def select_injected_output_audio(
    *,
    output_trace: Path,
    injection_at: datetime | None,
    max_seconds: float,
) -> tuple[bytes, int] | None:
    if injection_at is None or not output_trace.exists():
        return None

    chunks: list[bytes] = []
    sample_rate = 48000
    captured_samples = 0
    started = False
    last_timestamp: datetime | None = None

    with output_trace.open(newline="") as file:
        for row in csv.DictReader(file):
            timestamp = parse_trace_time(row.get("utc", ""))
            if timestamp is None or timestamp < injection_at:
                continue

            try:
                row_sample_rate = int(row.get("sample_rate", "48000"))
                output_samples = int(row.get("output_samples", "0"))
                peak = int(row.get("peak", "0"))
            except ValueError:
                continue
            if peak < 512:
                if started and last_timestamp is not None and (timestamp - last_timestamp).total_seconds() > 0.35:
                    break
                continue

            path = Path(row.get("path", ""))
            if not path.name.startswith("SinkBuffer-") or not path.is_file():
                continue

            if started and last_timestamp is not None and (timestamp - last_timestamp).total_seconds() > 0.35:
                break

            started = True
            sample_rate = row_sample_rate
            chunks.append(path.read_bytes())
            captured_samples += output_samples
            last_timestamp = timestamp

            if captured_samples >= int(sample_rate * max_seconds):
                break

    if not chunks:
        return None
    return b"".join(chunks), sample_rate


def postprocess_voice_pcm(pcm: bytes, *, sample_rate: int) -> bytes:
    if len(pcm) < 2:
        return pcm
    if len(pcm) % 2:
        pcm = pcm[:-1]

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return pcm

    threshold = int(os.environ.get("TTSMODACHI_LTD_VOICE_TRIM_THRESHOLD", "96"))
    start = 0
    end = len(samples)
    while start < end and abs(samples[start]) < threshold:
        start += 1
    while end > start and abs(samples[end - 1]) < threshold:
        end -= 1

    pad = int(sample_rate * float(os.environ.get("TTSMODACHI_LTD_VOICE_TRIM_PAD_SECONDS", "0.04")))
    start = max(0, start - pad)
    end = min(len(samples), end + pad)
    samples = samples[start:end]
    if not samples:
        return b""

    peak = max(abs(sample) for sample in samples)
    if peak > 0:
        target_peak = int(os.environ.get("TTSMODACHI_LTD_VOICE_TARGET_PEAK", "26000"))
        max_gain = float(os.environ.get("TTSMODACHI_LTD_VOICE_MAX_GAIN", "4.0"))
        gain = min(target_peak / peak, max_gain)
        if abs(gain - 1.0) > 0.01:
            for index, sample in enumerate(samples):
                samples[index] = int(max(min(round(sample * gain), 32767), -32768))

    fade_samples = min(int(sample_rate * float(os.environ.get("TTSMODACHI_LTD_VOICE_FADE_SECONDS", "0.006"))), len(samples) // 2)
    for index in range(fade_samples):
        factor = index / max(fade_samples, 1)
        samples[index] = int(round(samples[index] * factor))
        samples[-index - 1] = int(round(samples[-index - 1] * factor))

    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def apply_ltd_voice_params(pcm: bytes, *, sample_rate: int, voice: VoiceParams) -> bytes:
    if not pcm:
        return pcm

    pitch_factor = 2 ** (((voice.pitch - 50) / 100) * 0.85)
    speed_factor = 0.55 + (voice.speed / 100) * 0.9
    tone_gain = ((voice.tone - 50) / 50) * 5
    if (
        abs(pitch_factor - 1.0) < 0.02
        and abs(speed_factor - 1.0) < 0.02
        and abs(tone_gain) < 0.25
    ):
        return pcm

    ffmpeg = shutil.which(os.environ.get("TTSMODACHI_FFMPEG", "ffmpeg"))
    if not ffmpeg:
        return pcm

    filters = [
        f"asetrate={sample_rate * pitch_factor:.3f}",
        f"aresample={sample_rate}",
        *atempo_filters(1 / pitch_factor),
        *atempo_filters(speed_factor),
    ]
    if abs(tone_gain) >= 0.25:
        filters.append(f"equalizer=f=3200:t=q:w=1:g={tone_gain:.3f}")

    command = [
        ffmpeg,
        "-v",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-af",
        ",".join(filters),
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            input=pcm,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=float(os.environ.get("TTSMODACHI_LTD_VOICE_FFMPEG_TIMEOUT_SECONDS", "5")),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return pcm
    return result.stdout if result.returncode == 0 and result.stdout else pcm


def atempo_filters(value: float) -> list[str]:
    filters: list[str] = []
    while value < 0.5:
        filters.append("atempo=0.5")
        value /= 0.5
    while value > 2.0:
        filters.append("atempo=2.0")
        value /= 2.0
    filters.append(f"atempo={value:.6f}")
    return filters


def first_injection_time(block_trace: Path, text_byte_length: int) -> datetime | None:
    if not block_trace.exists():
        return None
    with block_trace.open(newline="") as file:
        for row in csv.DictReader(file):
            if row.get("relative_address") != "0x444660":
                continue
            try:
                length = int(row.get("x3", "0"), 16)
            except ValueError:
                continue
            if length != text_byte_length:
                continue
            timestamp = parse_trace_time(row.get("utc", ""))
            if timestamp is not None:
                return timestamp
    return None


def parse_trace_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if "." in value:
            head, tail = value.split(".", 1)
            fraction, suffix = tail[:7], tail[7:]
            value = f"{head}.{fraction[:6]}{suffix}"
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def pcm_s16le_to_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def env_bool_default(name: str, fallback: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ltd_dsp_trace_enabled(appliance_mode: bool) -> bool:
    return env_bool_default("TTSMODACHI_LTD_ENABLE_DSP_TRACE", not appliance_mode)


def ltd_boot_input_enabled(appliance_mode: bool) -> bool:
    return env_bool_default("TTSMODACHI_LTD_BOOT_INPUT", False)


def ltd_prewarm_primer_enabled() -> bool:
    return env_bool_default("TTSMODACHI_LTD_PREWARM_PRIMER", False)


def ltd_data_has_appliance_seed(data_dir: Path) -> bool:
    return (
        (data_dir / "system" / "Profiles.json").is_file()
        and (data_dir / "bis" / "user" / "save" / "0000000000000001" / "0" / "Mii.sav").is_file()
        and (data_dir / "bis" / "system" / "save" / "8000000000000030" / "0" / "MiiDatabase.dat").is_file()
    )


def ltd_mute_device_sink_value(appliance_mode: bool) -> str:
    return "true" if env_bool_default("TTSMODACHI_LTD_MUTE_DEVICE_SINK", appliance_mode) else "false"


def ltd_dummy_audio_value(appliance_mode: bool) -> str:
    return "true" if env_bool_default("TTSMODACHI_LTD_DUMMY_AUDIO", appliance_mode) else "false"

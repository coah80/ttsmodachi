from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import socket
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import env_float, env_int, env_setdefault, env_value
from .ltd_switch import LtdRenderRequest, LtdSwitchWorker
from .voices import VoiceParams


ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "api"
WORKER_QUEUE_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class WorkerSpec:
    rom: str
    lang_id: int
    port: int
    name: str


@dataclass(frozen=True)
class RenderPayload:
    text: str
    voice: VoiceParams
    mode: str = "text"


def find_free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _worker_loop(spec: WorkerSpec, inbox: mp.Queue, outbox: mp.Queue) -> None:
    os.environ.setdefault("CITRA_MAX_RUNTIME_SECONDS", "0")
    env_setdefault("TTSMODACHI_POLL_INTERVAL", "0.01")
    idle_suspend_seconds = env_float("TTSMODACHI_IDLE_SUSPEND_SECONDS", 10)
    idle_resume_timeout = env_float("TTSMODACHI_IDLE_RESUME_TIMEOUT_MS", 1000) / 1000
    render_ready_timeout = env_float("TTSMODACHI_RENDER_READY_TIMEOUT_SECONDS", 2)
    sys.path.insert(0, str(API_DIR))

    import citra  # type: ignore

    citra.CITRA_PORT = spec.port
    import tts  # type: ignore

    tts.citra.CITRA_PORT = spec.port
    tts.emu = citra.Citra(port=spec.port)
    paused = False
    active_job_count = 0
    last_activity_at = time.time()
    last_render_ms: float | None = None
    resume_count = 0
    restart_count = 0
    render_retry_count = 0
    last_recovery_reason: str | None = None
    last_error: str | None = None

    def citra_pid() -> int | None:
        process = getattr(tts, "emulatorProcess", None)
        return process.pid if process is not None and process.poll() is None else None

    def state_payload(event: str) -> dict[str, object]:
        return {
            "type": "state",
            "event": event,
            "worker": spec.name,
            "citra_pid": citra_pid(),
            "paused": paused,
            "active_job_count": active_job_count,
            "last_activity_at": last_activity_at,
            "last_render_ms": last_render_ms,
            "resume_count": resume_count,
            "restart_count": restart_count,
            "render_retry_count": render_retry_count,
            "last_recovery_reason": last_recovery_reason,
            "last_error": last_error,
        }

    def publish_state(event: str) -> None:
        outbox.put(state_payload(event))

    def log_event(message: str) -> None:
        print(f"[ttsmodachi-worker:{spec.name}] {message}", flush=True)

    def start_emulator() -> None:
        nonlocal paused, last_activity_at, last_error
        tts.emu = citra.Citra(port=spec.port)
        tts.startEmulator(spec.rom, spec.lang_id)
        paused = False
        last_activity_at = time.time()
        last_error = None

    def restart_emulator(reason: str) -> None:
        nonlocal paused, restart_count, last_activity_at, last_error, last_recovery_reason
        restart_count += 1
        last_error = reason
        last_recovery_reason = reason
        log_event(f"restarting Citra: {reason}")
        try:
            if paused and citra_pid() is not None:
                os.kill(citra_pid(), signal.SIGCONT)
        except ProcessLookupError:
            pass
        try:
            tts.killEmulator()
        except Exception:
            pass
        paused = False
        start_emulator()
        last_activity_at = time.time()
        publish_state("restarted")

    def resume_emulator() -> None:
        nonlocal paused, resume_count, last_activity_at, last_error
        if not paused:
            process = getattr(tts, "emulatorProcess", None)
            if process is None:
                restart_emulator("Citra process missing")
            elif process.poll() is not None:
                restart_emulator(f"Citra exited with code {process.returncode}")
            return
        pid = citra_pid()
        if pid is None:
            restart_emulator("Citra process missing while paused")
            return
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            paused = False
            restart_emulator("Citra process disappeared while paused")
            return
        paused = False
        resume_count += 1
        last_activity_at = time.time()
        last_error = None
        publish_state("resumed")
        log_event(f"resumed Citra pid={pid}")
        try:
            tts.waitForStatus(1, timeout=idle_resume_timeout)
        except Exception as error:
            restart_emulator(f"Citra did not respond after resume: {error}")

    def render_once(payload: dict[str, Any], voice: VoiceParams) -> bytes:
        if payload["mode"] == "sing":
            audio = tts.singText(
                payload["text"],
                voice.pitch,
                voice.speed,
                voice.quality,
                voice.tone,
                voice.accent,
                voice.engine_intonation(),
                voice.lang_id(),
                ready_timeout=render_ready_timeout,
            )
        else:
            audio = tts.generateText(
                payload["text"],
                voice.pitch,
                voice.speed,
                voice.quality,
                voice.tone,
                voice.accent,
                voice.engine_intonation(),
                voice.lang_id(),
                ready_timeout=render_ready_timeout,
            )
        if audio is None:
            raise RuntimeError("Renderer returned no audio")
        return audio

    def render_with_recovery(payload: dict[str, Any], voice: VoiceParams) -> bytes:
        nonlocal render_retry_count, last_recovery_reason
        try:
            return render_once(payload, voice)
        except Exception as first_error:
            reason = f"render failed before retry: {first_error}"
            last_recovery_reason = reason
            render_retry_count += 1
            log_event(reason)
            restart_emulator(reason)
            return render_once(payload, voice)

    def maybe_suspend_emulator() -> None:
        nonlocal paused, last_activity_at, last_error
        if active_job_count:
            return
        process = getattr(tts, "emulatorProcess", None)
        if process is None:
            return
        if process.poll() is not None:
            try:
                paused = False
                restart_emulator(f"Citra exited with code {process.returncode} while idle")
            except Exception:
                last_error = traceback.format_exc()
                log_event(f"failed to restart idle Citra: {last_error}")
                publish_state("restart_error")
            return
        if idle_suspend_seconds <= 0 or paused:
            return
        if time.time() - last_activity_at < idle_suspend_seconds:
            return
        pid = process.pid
        try:
            os.kill(pid, signal.SIGSTOP)
        except ProcessLookupError:
            return
        paused = True
        log_event(f"paused Citra pid={pid} after {round(time.time() - last_activity_at, 2)}s idle")
        publish_state("paused")

    try:
        start_emulator()
        outbox.put({"type": "ready", "worker": spec.name, "state": state_payload("ready")})
    except Exception:
        outbox.put({"type": "startup_error", "worker": spec.name, "error": traceback.format_exc()})

    while True:
        try:
            message = inbox.get(timeout=WORKER_QUEUE_POLL_SECONDS)
        except queue.Empty:
            maybe_suspend_emulator()
            continue

        if message is None:
            break

        job_id = message["job_id"]
        payload = message["payload"]
        started = time.perf_counter()
        active_job_count += 1
        last_activity_at = time.time()
        try:
            voice = VoiceParams.from_mapping(payload["voice"])
            if voice.rom() != spec.rom:
                raise ValueError(f"Worker {spec.name} cannot render ROM {voice.rom()}")
            if payload["mode"] not in {"text", "sing"}:
                raise ValueError(f"Unsupported render mode: {payload['mode']}")

            resume_emulator()
            audio = render_with_recovery(payload, voice)
            last_error = None
            outbox.put(
                {
                    "type": "result",
                    "job_id": job_id,
                    "audio": audio,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "state": state_payload("result"),
                }
            )
        except Exception:
            last_error = traceback.format_exc()
            outbox.put({"type": "error", "job_id": job_id, "error": last_error, "state": state_payload("error")})
        finally:
            active_job_count = max(0, active_job_count - 1)
            last_render_ms = round((time.perf_counter() - started) * 1000, 2)
            last_activity_at = time.time()
            publish_state("idle")

    try:
        if paused and citra_pid() is not None:
            os.kill(citra_pid(), signal.SIGCONT)
        tts.killEmulator()
    except Exception:
        pass


class WorkerLane:
    def __init__(self, spec: WorkerSpec) -> None:
        self.spec = spec
        self.inbox: mp.Queue | None = None
        self.outbox: mp.Queue | None = None
        self.pending: dict[str, Future[dict[str, Any]]] = {}
        self.pending_lock = threading.Lock()
        self.lifecycle_lock = threading.RLock()
        self.ready = threading.Event()
        self.startup_failed = False
        self.last_error: str | None = None
        self.process: mp.Process | None = None
        self.results_thread: threading.Thread | None = None
        self.citra_pid: int | None = None
        self.paused = False
        self.active_job_count = 0
        self.last_activity_at: float | None = None
        self.last_render_ms: float | None = None
        self.resume_count = 0
        self.worker_restart_count = 0
        self.process_restart_count = 0
        self.render_retry_count = 0
        self.last_recovery_reason: str | None = None

    def start(self) -> None:
        with self.lifecycle_lock:
            if self.process is not None and self.process.is_alive():
                return
            self.ready.clear()
            self.startup_failed = False
            self.last_error = None
            self.citra_pid = None
            self.paused = False
            self.active_job_count = 0
            self.last_activity_at = None
            self.last_render_ms = None
            self.resume_count = 0
            self.worker_restart_count = 0
            self.render_retry_count = 0
            self.last_recovery_reason = None
            self.inbox = mp.Queue()
            self.outbox = mp.Queue()
            self.process = mp.Process(target=_worker_loop, args=(self.spec, self.inbox, self.outbox), daemon=True)
            self.results_thread = threading.Thread(target=self._result_loop, args=(self.process, self.outbox), daemon=True)
            self.process.start()
            self.results_thread.start()

    def stop(self) -> None:
        process = self.process
        inbox = self.inbox
        if process is not None and process.is_alive():
            if inbox is not None:
                inbox.put(None)
            process.join(timeout=5)
        if process is not None and process.is_alive():
            process.kill()
        self._fail_pending(RuntimeError(f"Renderer worker {self.spec.name} stopped"))

    def restart(self) -> None:
        with self.lifecycle_lock:
            self.process_restart_count += 1
            self.stop()
            self.start()

    def render(self, payload: RenderPayload, timeout: float) -> dict[str, Any]:
        if self.process is None or not self.process.is_alive():
            self.start()
        if not self.ready.wait(timeout=min(timeout, 15.0)):
            raise RuntimeError(f"Renderer worker {self.spec.name} is not ready")
        if self.startup_failed:
            raise RuntimeError(f"Renderer worker {self.spec.name} failed startup: {self.last_error}")

        inbox = self.inbox
        if inbox is None:
            raise RuntimeError(f"Renderer worker {self.spec.name} has no command queue")
        job_id = str(uuid.uuid4())
        future: Future[dict[str, Any]] = Future()
        with self.pending_lock:
            self.pending[job_id] = future
        inbox.put(
            {
                "job_id": job_id,
                "payload": {
                    "text": payload.text,
                    "voice": payload.voice.to_dict(),
                    "mode": payload.mode,
                },
            }
        )
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as error:
            with self.pending_lock:
                self.pending.pop(job_id, None)
            self.restart()
            raise TimeoutError(f"Renderer worker {self.spec.name} timed out") from error

    def pending_count(self) -> int:
        with self.pending_lock:
            return len(self.pending)

    def _result_loop(self, process: mp.Process, outbox: mp.Queue) -> None:
        while True:
            try:
                message = outbox.get(timeout=1)
            except queue.Empty:
                if not process.is_alive():
                    self._fail_pending(RuntimeError(f"Renderer worker {self.spec.name} exited"))
                    return
                continue

            message_type = message.get("type")
            if message_type == "ready":
                self._apply_state(message.get("state"))
                self.ready.set()
            elif message_type == "startup_error":
                self.startup_failed = True
                self.last_error = message["error"]
                self.ready.set()
            elif message_type == "state":
                self._apply_state(message)
            elif message_type in {"result", "error"}:
                self._apply_state(message.get("state"))
                job_id = message["job_id"]
                with self.pending_lock:
                    future = self.pending.pop(job_id, None)
                if future is None:
                    continue
                if message_type == "result":
                    future.set_result(message)
                else:
                    future.set_exception(RuntimeError(message["error"]))

    def _apply_state(self, state: object) -> None:
        if not isinstance(state, dict):
            return
        if "citra_pid" in state:
            self.citra_pid = state["citra_pid"] if isinstance(state.get("citra_pid"), int) else None
        self.paused = bool(state.get("paused", self.paused))
        self.active_job_count = int(state.get("active_job_count", self.active_job_count) or 0)
        self.last_activity_at = (
            float(state["last_activity_at"])
            if isinstance(state.get("last_activity_at"), (int, float))
            else self.last_activity_at
        )
        self.last_render_ms = (
            float(state["last_render_ms"])
            if isinstance(state.get("last_render_ms"), (int, float))
            else self.last_render_ms
        )
        self.resume_count = int(state.get("resume_count", self.resume_count) or 0)
        self.worker_restart_count = int(state.get("restart_count", self.worker_restart_count) or 0)
        self.render_retry_count = int(state.get("render_retry_count", self.render_retry_count) or 0)
        if state.get("last_recovery_reason"):
            self.last_recovery_reason = str(state["last_recovery_reason"])
        if state.get("last_error"):
            self.last_error = str(state["last_error"])

    def _fail_pending(self, error: Exception) -> None:
        with self.pending_lock:
            pending = list(self.pending.values())
            self.pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)


class RendererPool:
    def __init__(self, specs: list[WorkerSpec], render_timeout: float = 20.0, ltd_worker: LtdSwitchWorker | None = None) -> None:
        self.render_timeout = render_timeout
        self.ltd_worker = ltd_worker
        self.lanes_by_rom: dict[str, list[WorkerLane]] = {}
        self.next_index: dict[str, int] = {}
        for spec in specs:
            self.lanes_by_rom.setdefault(spec.rom, []).append(WorkerLane(spec))
            self.next_index.setdefault(spec.rom, 0)

    @classmethod
    def from_env(cls) -> "RendererPool":
        render_timeout = env_float("TTSMODACHI_RENDER_TIMEOUT", 20)
        specs: list[WorkerSpec] = []
        worker_roms = [rom.strip().upper() for rom in (env_value("TTSMODACHI_WORKER_ROMS", "US") or "").split(",") if rom.strip()]
        for rom in worker_roms:
            if rom == "LTD":
                continue
            count = env_int(f"TTSMODACHI_{rom}_WORKERS", 1)
            lang_id = env_int(f"TTSMODACHI_{rom}_LANG_ID", 1)
            for index in range(count):
                specs.append(WorkerSpec(rom=rom, lang_id=lang_id, port=find_free_udp_port(), name=f"{rom}-{index + 1}"))
        ltd_worker = None
        if "LTD" in worker_roms or (env_value("TTSMODACHI_LTD_ENABLED", "") or "").lower() in {"1", "true", "yes"}:
            game_path = Path(env_value("TTSMODACHI_LTD_GAME_PATH", "") or "")
            ryubing_path = Path(env_value("TTSMODACHI_LTD_RYUBING_PATH", "ryubing-work/ryubing") or "ryubing-work/ryubing")
            ltd_worker = LtdSwitchWorker(
                ryubing_path=ryubing_path,
                game_path=game_path,
                data_dir=Path(env_value("TTSMODACHI_LTD_DATA_DIR", "ltd-work/ryubing-data") or "ltd-work/ryubing-data"),
                work_dir=Path(env_value("TTSMODACHI_LTD_WORK_DIR", "ltd-work/ltd-renderer") or "ltd-work/ltd-renderer"),
                dotnet_root=env_value("TTSMODACHI_LTD_DOTNET_ROOT", os.environ.get("DOTNET_ROOT", "")),
                timeout_seconds=env_float("TTSMODACHI_LTD_TIMEOUT_SECONDS", 150),
            )
        return cls(specs, render_timeout=render_timeout, ltd_worker=ltd_worker)

    def start(self) -> None:
        for lane in self._lanes():
            lane.start()
        if self.ltd_worker is not None:
            self.ltd_worker.start()

    def stop(self) -> None:
        for lane in self._lanes():
            lane.stop()
        if self.ltd_worker is not None:
            self.ltd_worker.stop()

    def render(self, payload: RenderPayload) -> dict[str, Any]:
        if payload.voice.rom() == "LTD":
            if self.ltd_worker is None:
                raise RuntimeError("No LTD Switch renderer configured")
            started = time.perf_counter()
            audio = self.ltd_worker.render(LtdRenderRequest(text=payload.text, voice=payload.voice, mode=payload.mode))
            return {"type": "result", "audio": audio, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}
        lanes = self.lanes_by_rom.get(payload.voice.rom())
        if not lanes:
            raise RuntimeError(f"No renderer worker configured for ROM {payload.voice.rom()}")
        lane = min(lanes, key=lambda worker: worker.pending_count())
        return lane.render(payload, timeout=self.render_timeout)

    def health(self) -> dict[str, Any]:
        return {
            "workers": [
                {
                    "name": lane.spec.name,
                    "rom": lane.spec.rom,
                    "port": lane.spec.port,
                    "pid": lane.process.pid if lane.process else None,
                    "worker_pid": lane.process.pid if lane.process else None,
                    "citra_pid": lane.citra_pid,
                    "alive": lane.process.is_alive() if lane.process else False,
                    "ready": lane.ready.is_set(),
                    "paused": lane.paused,
                    "active_job_count": lane.active_job_count,
                    "idle_seconds": (
                        round(max(0.0, time.time() - lane.last_activity_at), 2)
                        if lane.last_activity_at is not None
                        else None
                    ),
                    "last_render_ms": lane.last_render_ms,
                    "resume_count": lane.resume_count,
                    "restart_count": lane.process_restart_count + lane.worker_restart_count,
                    "render_retry_count": lane.render_retry_count,
                    "last_recovery_reason": lane.last_recovery_reason,
                    "last_error": lane.last_error,
                }
                for lane in self._lanes()
            ],
            "ltd_switch": self.ltd_worker.health() if self.ltd_worker else None,
        }

    def _lanes(self) -> list[WorkerLane]:
        return [lane for lanes in self.lanes_by_rom.values() for lane in lanes]

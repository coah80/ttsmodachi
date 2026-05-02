#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LTD Ryubing staging harness and capture PCM voice streams.")
    parser.add_argument("--ryubing", type=Path, default=Path("ryubing-work/ryubing"), help="Ryubing repo/build directory.")
    parser.add_argument("--game", type=Path, required=True, help="Owned Tomodachi Life: Living the Dream NSP/XCI path.")
    parser.add_argument("--data-dir", type=Path, default=Path("ltd-work/ryubing-data"), help="Isolated Ryubing data dir.")
    parser.add_argument("--out-dir", type=Path, default=Path("ltd-work/probe"), help="Probe output directory.")
    parser.add_argument("--seconds", type=float, default=180.0, help="Maximum run time.")
    parser.add_argument("--dotnet-root", default=os.environ.get("DOTNET_ROOT", "/opt/homebrew/Cellar/dotnet/10.0.105/libexec"))
    parser.add_argument("--jit", action="store_true", help="Disable Apple Hypervisor so ARMeilleure guest-address tracing can run.")
    parser.add_argument("--trace-exec", action="store_true", help="Use managed dispatch so targeted guest addresses log repeated execution hits.")
    parser.add_argument("--trace-exec-only", action="store_true", help="Log ExecuteSingle hits only, not Translate hits.")
    parser.add_argument("--guest-base", default="0x8506000", help="LTD main NSO guest base used for relative trace addresses.")
    parser.add_argument("--trace-main", action="store_true", help="Trace all translated LTD main NSO addresses instead of only candidate addresses.")
    parser.add_argument("--trace-registers", action="store_true", help="Include selected x registers on guest trace hits.")
    parser.add_argument("--guest-max-events", default="100000", help="Maximum guest trace rows.")
    parser.add_argument("--guest-start-seconds", default="", help="Delay guest trace logging until N seconds after emulator start.")
    parser.add_argument("--guest-duration-seconds", default="", help="Stop guest trace logging after this many seconds from the trace start.")
    parser.add_argument("--trace-writes", action="store_true", help="Trace guest stores that overlap --memory-write-ranges.")
    parser.add_argument("--memory-write-ranges", default="", help="Comma-separated guest address ranges to watch for writes.")
    parser.add_argument("--memory-write-max-events", default="20000", help="Maximum memory write trace rows.")
    parser.add_argument("--memory-write-start-seconds", default="", help="Delay memory write tracing until N seconds after emulator start.")
    parser.add_argument("--memory-write-duration-seconds", default="", help="Stop memory write tracing after this many seconds from the trace start.")
    parser.add_argument("--trace-blocks", action="store_true", help="Trace translated basic-block entry hits with guest register snapshots.")
    parser.add_argument("--block-addrs", default="", help="Comma-separated absolute or main-relative basic-block addresses to trace.")
    parser.add_argument("--block-max-events", default="50000", help="Maximum block trace rows.")
    parser.add_argument(
        "--guest-addrs",
        default=(
            "0x5fffe8,0x600330,0x600640,0x600808,0x600bec,0x600d78,"
            "0xac9710,0xac9da0,0xb998f8,0xc09074,0xc5fa84,0xcbbaf8,"
            "0xd2ad74,0xd80f24,0xe033a4,0xe7db74,0xee52f4,0xf4c9f0,"
            "0xfb4cf4,0x1015e10"
        ),
        help="Comma-separated absolute or main-relative guest addresses to trace.",
    )
    parser.add_argument("--no-clean", action="store_true", help="Keep previous probe output.")
    return parser.parse_args()


def build_touch_script() -> str:
    events: list[str] = []
    for frame in range(1500, 90000, 1500):
        events.append(f"{frame}:700:610:35")
    for frame in range(60000, 112000, 3500):
        events.append(f"{frame}:1110:75:35")
    return ";".join(events)


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    ryubing = args.ryubing if args.ryubing.is_absolute() else root / args.ryubing
    data_dir = args.data_dir if args.data_dir.is_absolute() else root / args.data_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    game = args.game if args.game.is_absolute() else root / args.game

    if not args.no_clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    live_input = out_dir / "live-input.txt"
    live_touch = out_dir / "live-touch.txt"
    live_input.write_text("\n")
    live_touch.write_text("\n")

    log_path = out_dir / "ryubing.log"
    audio_trace = out_dir / "audio.csv"
    input_trace = out_dir / "input.csv"
    guest_trace = out_dir / "guest-trace.csv"
    memory_write_trace = out_dir / "memory-writes.csv"
    block_trace = out_dir / "block-trace.csv"
    dump_dir = out_dir / "audio-dumps"
    dump_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "DOTNET_ROOT": args.dotnet_root,
            "RYUJINX_HEADLESS_SWKBD_AUTO_ACCEPT": "true",
            "RYUJINX_HEADLESS_SWKBD_TEXTS": "Cole|TTSmodachi|Ryujinx|Tomodachi",
            "RYUJINX_TTSMODACHI_AUTO_A": "true",
            "RYUJINX_TTSMODACHI_AUTO_A_START_FRAME": "1500",
            "RYUJINX_TTSMODACHI_AUTO_A_INTERVAL_FRAMES": "240",
            "RYUJINX_TTSMODACHI_AUTO_A_DURATION_FRAMES": "4",
            "RYUJINX_TTSMODACHI_TOUCH_SCRIPT": build_touch_script(),
            "RYUJINX_TTSMODACHI_TOUCH_FILE": str(live_touch),
            "RYUJINX_TTSMODACHI_INPUT_FILE": str(live_input),
            "RYUJINX_TTSMODACHI_INPUT_TRACE": str(input_trace),
            "RYUJINX_TTSMODACHI_AUDIO_TRACE": str(audio_trace),
            "RYUJINX_TTSMODACHI_AUDIO_TRACE_FORMATS": "PcmInt16,PcmFloat",
            "RYUJINX_TTSMODACHI_AUDIO_TRACE_MIN_PEAK": "0.001",
            "RYUJINX_TTSMODACHI_AUDIO_TRACE_MAX_EVENTS": "10000",
            "RYUJINX_TTSMODACHI_AUDIO_DUMP_DIR": str(dump_dir),
            "RYUJINX_TTSMODACHI_AUDIO_DUMP_MAX_SECONDS": "5",
        }
    )
    if args.guest_addrs:
        env["RYUJINX_TTSMODACHI_GUEST_TRACE"] = str(guest_trace)
        env["RYUJINX_TTSMODACHI_GUEST_TRACE_BASE"] = args.guest_base
        env["RYUJINX_TTSMODACHI_GUEST_TRACE_ADDRS"] = args.guest_addrs
        env["RYUJINX_TTSMODACHI_GUEST_TRACE_MAX_EVENTS"] = args.guest_max_events
        if args.guest_start_seconds:
            env["RYUJINX_TTSMODACHI_GUEST_TRACE_START_SECONDS"] = args.guest_start_seconds
        if args.guest_duration_seconds:
            env["RYUJINX_TTSMODACHI_GUEST_TRACE_DURATION_SECONDS"] = args.guest_duration_seconds
        if args.trace_main:
            env["RYUJINX_TTSMODACHI_GUEST_TRACE_RANGE"] = "0x0-0x25ce6a0"
        if args.trace_registers:
            env["RYUJINX_TTSMODACHI_GUEST_TRACE_REGISTERS"] = "true"
    if args.jit:
        env["RYUJINX_TTSMODACHI_DISABLE_HYPERVISOR"] = "true"
    if args.trace_exec:
        env["RYUJINX_TTSMODACHI_MANAGED_DISPATCH"] = "true"
    if args.trace_exec_only:
        env["RYUJINX_TTSMODACHI_MANAGED_DISPATCH"] = "true"
        env["RYUJINX_TTSMODACHI_GUEST_TRACE_SOURCES"] = "ExecuteSingle"
    if args.trace_writes:
        if not args.memory_write_ranges:
            raise SystemExit("--trace-writes requires --memory-write-ranges")
        env["RYUJINX_TTSMODACHI_MEMORY_WRITE_TRACE"] = str(memory_write_trace)
        env["RYUJINX_TTSMODACHI_MEMORY_WRITE_RANGES"] = args.memory_write_ranges
        env["RYUJINX_TTSMODACHI_MEMORY_WRITE_MAX_EVENTS"] = args.memory_write_max_events
        if args.memory_write_start_seconds:
            env["RYUJINX_TTSMODACHI_MEMORY_WRITE_START_SECONDS"] = args.memory_write_start_seconds
        if args.memory_write_duration_seconds:
            env["RYUJINX_TTSMODACHI_MEMORY_WRITE_DURATION_SECONDS"] = args.memory_write_duration_seconds
    if args.trace_blocks:
        if not args.block_addrs:
            raise SystemExit("--trace-blocks requires --block-addrs")
        env["RYUJINX_TTSMODACHI_BLOCK_TRACE"] = str(block_trace)
        env["RYUJINX_TTSMODACHI_GUEST_TRACE_BASE"] = args.guest_base
        env["RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS"] = args.block_addrs
        env["RYUJINX_TTSMODACHI_BLOCK_TRACE_MAX_EVENTS"] = args.block_max_events

    cmd = [
        "./build/Ryujinx",
        "--no-gui",
        "--root-data-dir",
        str(data_dir),
        "--disable-file-logging",
        "--disable-shader-cache",
        "--disable-ptc",
        "--ignore-missing-services",
        "--skip-user-profiles-manager",
        "--system-language",
        "AmericanEnglish",
        "--system-region",
        "USA",
    ]
    if args.jit:
        cmd.extend(["--use-hypervisor", "false", "--memory-manager-mode", "SoftwarePageTable"])
    cmd.extend(["--enable-debug-logs", str(game)])

    started_at = time.monotonic()
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(cmd, cwd=ryubing, env=env, stdout=log_file, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    summary = {
        "returncode": process.returncode,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "log": str(log_path),
        "audio_trace": str(audio_trace) if audio_trace.exists() else None,
        "input_trace": str(input_trace) if input_trace.exists() else None,
        "guest_trace": str(guest_trace) if guest_trace.exists() else None,
        "memory_write_trace": str(memory_write_trace) if memory_write_trace.exists() else None,
        "block_trace": str(block_trace) if block_trace.exists() else None,
        "dump_files": sorted(path.name for path in dump_dir.glob("*")),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

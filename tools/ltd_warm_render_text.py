#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keep the LTD appliance worker warm and render one or more texts to WAV files.")
    parser.add_argument("texts", nargs="+", help="Text messages to render.")
    parser.add_argument("--game", type=Path, default=Path(os.environ.get("TTSMODACHI_LTD_GAME_PATH", "ltd-work/ltd.nsp")))
    parser.add_argument("--ryubing", type=Path, default=Path("ryubing-work/ryubing"))
    parser.add_argument("--data-dir", type=Path, default=Path("ltd-work/ryubing-data"))
    parser.add_argument("--work-dir", type=Path, default=Path("ltd-work/ltd-warm-renderer"))
    parser.add_argument("--out-dir", type=Path, default=Path("ltd-work/ltd-renderer-proof/warm"))
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--prewarm-timeout", type=float, default=180.0)
    return parser.parse_args()


def safe_name(index: int, text: str) -> str:
    stem = "".join(char.lower() if char.isalnum() else "-" for char in text.strip())[:48].strip("-")
    return f"{index:02d}-{stem or 'tts'}.wav"


def main() -> int:
    root = Path.cwd()
    sys.path.insert(0, str(root))
    os.environ["TTSMODACHI_LTD_WARM"] = "1"
    os.environ["TTSMODACHI_LTD_APPLIANCE"] = "1"

    from ttsmodachi_bot.engines import ENGINE_LTD_SWITCH
    from ttsmodachi_bot.ltd_switch import LtdRenderRequest, LtdSwitchWorker
    from ttsmodachi_bot.voices import VoiceParams

    args = parse_args()
    worker = LtdSwitchWorker(
        ryubing_path=args.ryubing if args.ryubing.is_absolute() else root / args.ryubing,
        game_path=args.game if args.game.is_absolute() else root / args.game,
        data_dir=args.data_dir if args.data_dir.is_absolute() else root / args.data_dir,
        work_dir=args.work_dir if args.work_dir.is_absolute() else root / args.work_dir,
        timeout_seconds=args.timeout,
    )
    out_dir = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        started = time.perf_counter()
        worker.start()
        prewarmed = worker.wait_until_prewarmed(args.prewarm_timeout)
        print(f"prewarmed={prewarmed} elapsed={time.perf_counter() - started:.3f}s")
        if not prewarmed:
            health = worker.health()
            raise RuntimeError(f"LTD warm appliance did not prewarm; error={health.get('warm_prewarm_error')} dir={health.get('warm_dir')}")

        voice = VoiceParams(engine=ENGINE_LTD_SWITCH)
        for index, text in enumerate(args.texts, start=1):
            render_started = time.perf_counter()
            wav = worker.render(LtdRenderRequest(text=text, voice=voice))
            out = out_dir / safe_name(index, text)
            out.write_bytes(wav)
            print(f"{index} {time.perf_counter() - render_started:.3f}s {out}")
        return 0
    finally:
        worker.stop()


if __name__ == "__main__":
    raise SystemExit(main())

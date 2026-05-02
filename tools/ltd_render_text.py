#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render text through the LTD runtime TTS bridge.")
    parser.add_argument("text", help="Text to render.")
    parser.add_argument("--game", type=Path, default=Path(os.environ.get("TTSMODACHI_LTD_GAME_PATH", "ltd-work/ltd.nsp")))
    parser.add_argument("--ryubing", type=Path, default=Path("ryubing-work/ryubing"))
    parser.add_argument("--data-dir", type=Path, default=Path("ltd-work/ryubing-data"))
    parser.add_argument("--work-dir", type=Path, default=Path("ltd-work/ltd-renderer"))
    parser.add_argument("--out", type=Path, default=Path("ltd-work/ltd-renderer-proof/ltd-output.wav"))
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser.parse_args()


def main() -> int:
    root = Path.cwd()
    sys.path.insert(0, str(root))

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
    wav = worker.render(LtdRenderRequest(text=args.text, voice=VoiceParams(engine=ENGINE_LTD_SWITCH)))
    out = args.out if args.out.is_absolute() else root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(wav)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

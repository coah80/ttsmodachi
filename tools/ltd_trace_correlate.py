#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Correlate LTD Ryubing guest traces with PCM audio bursts.")
    parser.add_argument("probe_dir", type=Path, help="Probe output directory containing audio.csv and guest-trace.csv.")
    parser.add_argument("--before", type=float, default=0.15, help="Seconds before each audio burst to include.")
    parser.add_argument("--after", type=float, default=0.02, help="Seconds after each audio burst to include.")
    parser.add_argument("--limit", type=int, default=16, help="Maximum candidate addresses shown per burst.")
    return parser.parse_args()


def parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_audio_bursts(path: Path) -> list[tuple[dt.datetime, str, int]]:
    rows: list[list[str]] = []
    with path.open() as handle:
        for row in csv.reader(handle):
            if len(row) >= 12:
                rows.append(row)

    bursts: list[tuple[dt.datetime, str, int]] = []
    last_timestamp: dt.datetime | None = None
    last_node: str | None = None
    for row in rows:
        timestamp = parse_timestamp(row[0])
        node = row[3]
        if last_timestamp is None or node != last_node or (timestamp - last_timestamp).total_seconds() > 0.25:
            bursts.append((timestamp, node, int(row[1])))
        last_timestamp = timestamp
        last_node = node

    return bursts


def load_guest_trace(path: Path) -> list[tuple[dt.datetime, str, str, int]]:
    rows: list[tuple[dt.datetime, str, str, int]] = []
    with path.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append((parse_timestamp(row["utc"]), row["relative_address"], row["address"], int(row["event_count"])))
    return rows


def main() -> int:
    args = parse_args()
    audio_path = args.probe_dir / "audio.csv"
    trace_path = args.probe_dir / "guest-trace.csv"
    if not audio_path.exists():
        raise SystemExit(f"missing {audio_path}")
    if not trace_path.exists():
        raise SystemExit(f"missing {trace_path}")

    bursts = load_audio_bursts(audio_path)
    trace_rows = load_guest_trace(trace_path)
    print(f"audio_bursts={len(bursts)} trace_rows={len(trace_rows)}")

    for timestamp, node, event_count in bursts:
        candidates = [
            row
            for row in trace_rows
            if -args.before <= (row[0] - timestamp).total_seconds() <= args.after
        ]
        print(f"\n{timestamp.isoformat()} node={node} audio_event={event_count} candidates={len(candidates)}")
        for row in candidates[-args.limit :]:
            delta = (row[0] - timestamp).total_seconds()
            print(f"{delta:+.3f}s rel={row[1]} abs={row[2]} trace_event={row[3]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

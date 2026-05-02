#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


DEFAULT_COLUMNS = (
    "relative_source_pc",
    "relative_link_register",
    "link_register",
    "x0",
    "x1",
    "x2",
    "address",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LTD Ryubing memory-write trace CSVs.")
    parser.add_argument("trace", type=Path, help="memory-writes.csv path.")
    parser.add_argument("--limit", type=int, default=30, help="Rows per column.")
    parser.add_argument("--columns", default=",".join(DEFAULT_COLUMNS), help="Comma-separated columns to summarize.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = list(csv.DictReader(args.trace.open()))
    columns = [column.strip() for column in args.columns.split(",") if column.strip()]

    print(f"rows={len(rows)}")
    for column in columns:
        if not rows or column not in rows[0]:
            continue

        print(f"\n{column}")
        for value, count in Counter(row[column] for row in rows).most_common(args.limit):
            print(f"{value} {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

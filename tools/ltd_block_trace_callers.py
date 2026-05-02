#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


GUEST_BASE = 0x8506000
NSO_BASE = 0x8000000


def parse_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value, 10)
    except ValueError:
        return None


def to_relative(address: int, guest_base: int) -> int:
    return address - guest_base if address >= guest_base else address


def to_nso(address: int, guest_base: int, nso_base: int) -> int:
    return nso_base + to_relative(address, guest_base)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize probable indirect callers from LTD block-trace x30 values.")
    parser.add_argument("trace", type=Path, help="block-trace.csv path.")
    parser.add_argument("--guest-base", default=hex(GUEST_BASE), help="Runtime main module base.")
    parser.add_argument("--nso-base", default=hex(NSO_BASE), help="Static NSO base.")
    parser.add_argument("--limit", type=int, default=40, help="Rows per traced target.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    guest_base = parse_int(args.guest_base) or GUEST_BASE
    nso_base = parse_int(args.nso_base) or NSO_BASE
    rows = list(csv.DictReader(args.trace.open()))
    by_target: dict[str, Counter[int]] = defaultdict(Counter)
    by_target_lr: dict[str, Counter[int]] = defaultdict(Counter)

    for row in rows:
        relative = row.get("relative_address") or row.get("address") or "unknown"
        x30 = parse_int(row.get("x30", ""))
        if x30 is None or x30 < guest_base:
            continue
        by_target_lr[relative][x30] += 1
        if x30 >= 4:
            by_target[relative][x30 - 4] += 1

    print(f"rows={len(rows)}")
    for target in sorted(by_target):
        print(f"\ntarget={target}")
        print("probable_call_sites")
        for address, count in by_target[target].most_common(args.limit):
            print(
                f"  count={count:<5} guest={address:#x} rel={to_relative(address, guest_base):#x} nso={to_nso(address, guest_base, nso_base):#x}"
            )
        print("raw_x30")
        for address, count in by_target_lr[target].most_common(min(args.limit, 12)):
            print(
                f"  count={count:<5} guest={address:#x} rel={to_relative(address, guest_base):#x} nso={to_nso(address, guest_base, nso_base):#x}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


REGISTER_RE = re.compile(r"\b(x\d+)=((?:0x)?[0-9a-fA-F]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LTD appliance request dispatch register captures.")
    parser.add_argument("trace", type=Path, help="appliance.csv path.")
    parser.add_argument("--limit", type=int, default=12, help="Rows per address/register.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = list(csv.DictReader(args.trace.open()))
    by_address: dict[str, Counter[str]] = defaultdict(Counter)
    by_register: dict[str, Counter[str]] = defaultdict(Counter)
    total = 0

    for row in rows:
        if row.get("event") != "request-registers":
            continue
        reason = row.get("reason", "")
        total += 1
        address = row.get("address", "unknown")
        by_address[address][reason] += 1
        for register, value in REGISTER_RE.findall(reason):
            by_register[f"{address}:{register}"][value.lower()] += 1

    print(f"request_register_rows={total}")
    for address in sorted(by_address):
        print(f"\naddress={address}")
        for reason, count in by_address[address].most_common(args.limit):
            print(f"  count={count:<5} {reason}")

    for key in sorted(by_register):
        print(f"\n{key}")
        for value, count in by_register[key].most_common(args.limit):
            print(f"  count={count:<5} {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path


NAME_RE = re.compile(
    r"consumer-(?P<index>[0-9a-fA-F]+)-pc-(?P<pc>[0-9a-fA-F]+)-x(?P<reg>[0-9]+)-(?P<addr>[0-9a-fA-F]+)\.bin$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LTD consumer object dump fields.")
    parser.add_argument("dump_dir", type=Path, help="Directory created by TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_DIR.")
    parser.add_argument("--limit", type=int, default=12, help="Rows per group.")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum repeated field value count.")
    parser.add_argument("--pointer-low", default="0x6000000000", help="Lower bound for pointer-like values.")
    parser.add_argument("--pointer-high", default="0x7000000000", help="Upper bound for pointer-like values.")
    return parser.parse_args()


def parse_hex(value: str) -> int:
    value = value.strip()
    return int(value[2:] if value.lower().startswith("0x") else value, 16)


def words(data: bytes) -> list[int]:
    end = len(data) - (len(data) % 8)
    return [struct.unpack_from("<Q", data, offset)[0] for offset in range(0, end, 8)]


def main() -> int:
    args = parse_args()
    pointer_low = parse_hex(args.pointer_low)
    pointer_high = parse_hex(args.pointer_high)
    by_reg: dict[str, list[tuple[int, int, Path, list[int]]]] = defaultdict(list)

    for path in sorted(args.dump_dir.glob("consumer-*.bin")):
        match = NAME_RE.search(path.name)
        if match is None:
            continue
        by_reg[match.group("reg")].append(
            (
                int(match.group("index"), 16),
                parse_hex(match.group("addr")),
                path,
                words(path.read_bytes()),
            )
        )

    print(f"register_groups={len(by_reg)} files={sum(len(items) for items in by_reg.values())}")
    for reg in sorted(by_reg, key=lambda value: int(value)):
        items = by_reg[reg]
        addresses = Counter(address for _, address, _, _ in items)
        print(f"\nx{int(reg)} files={len(items)} unique_addresses={len(addresses)}")
        for address, count in addresses.most_common(args.limit):
            print(f"  address count={count:<5} {address:#x}")

        max_words = max((len(item[3]) for item in items), default=0)
        stable_offsets: list[tuple[int, int, int]] = []
        pointer_offsets: list[tuple[int, int, int]] = []
        small_offsets: list[tuple[int, int, int]] = []

        for word_index in range(max_words):
            counter: Counter[int] = Counter()
            for _, _, _, item_words in items:
                if word_index < len(item_words):
                    counter[item_words[word_index]] += 1
            if not counter:
                continue
            value, count = counter.most_common(1)[0]
            if count < args.min_count:
                continue
            offset = word_index * 8
            if count == len(items):
                stable_offsets.append((offset, value, count))
            if pointer_low <= value < pointer_high:
                pointer_offsets.append((offset, value, count))
            elif value <= 0x100000:
                small_offsets.append((offset, value, count))

        print("  stable_fields")
        for offset, value, count in stable_offsets[: args.limit]:
            print(f"    +{offset:#04x} count={count:<5} value={value:#x}")

        print("  pointer_like_fields")
        for offset, value, count in pointer_offsets[: args.limit]:
            print(f"    +{offset:#04x} count={count:<5} value={value:#x}")

        print("  small_fields")
        for offset, value, count in small_offsets[: args.limit]:
            print(f"    +{offset:#04x} count={count:<5} value={value:#x}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

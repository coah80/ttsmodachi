#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path


DEFAULT_GUEST_BASE = 0x8506000


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_segments(nso: bytes) -> list[tuple[str, int, int, int]]:
    if nso[:4] != b"NSO0":
        raise ValueError("input is not an NSO file")
    segments: list[tuple[str, int, int, int]] = []
    for index, name in enumerate(("text", "rodata", "data")):
        file_offset, mem_offset, size = struct.unpack_from("<III", nso, 0x10 + index * 0x10)
        segments.append((name, file_offset, mem_offset, size))
    return segments


def read_string(nso: bytes, segments: list[tuple[str, int, int, int]], address: int, guest_base: int, max_bytes: int) -> tuple[str, int, str] | None:
    relative = address - guest_base if address >= guest_base else address
    for name, file_offset, mem_offset, size in segments:
        if not mem_offset <= relative < mem_offset + size:
            continue
        offset = file_offset + relative - mem_offset
        end = nso.find(b"\0", offset, min(offset + max_bytes, len(nso)))
        raw = nso[offset : end if end >= 0 else min(offset + max_bytes, len(nso))]
        return name, relative, raw.decode("utf-8", "replace")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read null-terminated strings from LTD main NSO guest or relative addresses.")
    parser.add_argument("addresses", nargs="+", type=parse_int, help="Guest VAs or main-relative offsets.")
    parser.add_argument("--nso", type=Path, default=Path("ltd-work/analysis/main.uncompressed"))
    parser.add_argument("--guest-base", type=parse_int, default=DEFAULT_GUEST_BASE)
    parser.add_argument("--max-bytes", type=int, default=256)
    args = parser.parse_args()

    nso = args.nso.read_bytes()
    segments = parse_segments(nso)
    for address in args.addresses:
        result = read_string(nso, segments, address, args.guest_base, args.max_bytes)
        if result is None:
            relative = address - args.guest_base if address >= args.guest_base else address
            print(f"{address:#x} rel={relative:#x} unmapped")
            continue
        segment, relative, text = result
        print(f"{address:#x} rel={relative:#x} segment={segment} {text!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

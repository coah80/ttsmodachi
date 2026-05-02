#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path


NSO_BASE = 0x8000000
GUEST_BASE = 0x8506000


def parse_int(value: str) -> int:
    value = value.strip()
    if value.lower().startswith("0x"):
        return int(value, 16)
    try:
        return int(value, 10)
    except ValueError:
        return int(value, 16)


def normalize_to_nso_va(value: int, *, nso_base: int, guest_base: int) -> int:
    if value >= guest_base:
        return nso_base + (value - guest_base)
    if value >= nso_base:
        return value
    return nso_base + value


def to_guest_va(nso_va: int, *, nso_base: int, guest_base: int) -> int:
    return guest_base + (nso_va - nso_base)


def load_text_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".hex":
        return bytes.fromhex(data.decode().strip())
    return data


def branch_target(insn: int, pc: int) -> tuple[str, int] | None:
    if (insn & 0x7C000000) != 0x14000000:
        return None
    imm = insn & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    kind = "bl" if insn & 0x80000000 else "b"
    return kind, pc + imm * 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find direct ARM64 branch callers for LTD main NSO addresses.")
    parser.add_argument("addresses", nargs="+", help="Relative main offsets, runtime guest VAs, or NSO VAs.")
    parser.add_argument("--text", type=Path, default=Path("ltd-work/analysis/main.text.bin"), help="Uncompressed main text bytes or .hex dump.")
    parser.add_argument("--nso-base", default=hex(NSO_BASE), help="Static NSO base used by rizin.")
    parser.add_argument("--guest-base", default=hex(GUEST_BASE), help="Runtime main guest base.")
    parser.add_argument("--branches", action="store_true", help="Include non-link direct branches, not just BL calls.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum callers printed per address.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nso_base = parse_int(args.nso_base)
    guest_base = parse_int(args.guest_base)
    text = load_text_bytes(args.text)
    targets = [
        normalize_to_nso_va(parse_int(address), nso_base=nso_base, guest_base=guest_base)
        for address in args.addresses
    ]
    target_set = set(targets)
    callers: dict[int, list[tuple[int, str]]] = {target: [] for target in targets}

    for offset in range(0, len(text) - 4, 4):
        pc = nso_base + offset
        decoded = branch_target(struct.unpack_from("<I", text, offset)[0], pc)
        if decoded is None:
            continue
        kind, dest = decoded
        if kind != "bl" and not args.branches:
            continue
        if dest in target_set:
            callers[dest].append((pc, kind))

    for target in targets:
        rel = target - nso_base
        guest = to_guest_va(target, nso_base=nso_base, guest_base=guest_base)
        print(f"target nso={target:#x} rel={rel:#x} guest={guest:#x}")
        for pc, kind in callers[target][: args.limit]:
            print(f"  {kind} nso={pc:#x} rel={pc - nso_base:#x} guest={to_guest_va(pc, nso_base=nso_base, guest_base=guest_base):#x}")
        if len(callers[target]) > args.limit:
            print(f"  ... {len(callers[target]) - args.limit} more")
        print(f"  callers={len(callers[target])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


NSO_BASE = 0x8200000
GUEST_BASE = 0x8506000


@dataclass(frozen=True)
class Segment:
    name: str
    file_offset: int
    mem_offset: int
    size: int


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_segments(nso: bytes) -> list[Segment]:
    if nso[:4] != b"NSO0":
        raise ValueError("input is not an NSO file")
    names = ("text", "rodata", "data")
    segments: list[Segment] = []
    for index, name in enumerate(names):
        offset = 0x10 + index * 0x10
        file_offset, mem_offset, size = struct.unpack_from("<III", nso, offset)
        segments.append(Segment(name=name, file_offset=file_offset, mem_offset=mem_offset, size=size))
    return segments


def file_to_relative(segments: list[Segment], file_offset: int) -> int | None:
    for segment in segments:
        start = segment.file_offset
        end = start + segment.size
        if start <= file_offset < end:
            return segment.mem_offset + file_offset - start
    return None


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def decode_adrp(insn: int, pc: int) -> tuple[int, int] | None:
    if insn & 0x9F000000 != 0x90000000:
        return None
    immlo = (insn >> 29) & 0x3
    immhi = (insn >> 5) & 0x7FFFF
    imm = sign_extend((immhi << 2) | immlo, 21) << 12
    rd = insn & 0x1F
    return rd, (pc & ~0xFFF) + imm


def decode_add_imm(insn: int) -> tuple[int, int, int] | None:
    if insn & 0xFF000000 != 0x91000000:
        return None
    rd = insn & 0x1F
    rn = (insn >> 5) & 0x1F
    imm = (insn >> 10) & 0xFFF
    shift = (insn >> 22) & 0x3
    if shift == 1:
        imm <<= 12
    elif shift != 0:
        return None
    return rd, rn, imm


def find_strings(nso: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        index = nso.find(needle, start)
        if index < 0:
            return offsets
        offsets.append(index)
        start = index + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Find ARM64 ADRP+ADD references to strings in the LTD main NSO.")
    parser.add_argument("strings", nargs="+", help="ASCII string fragments to find and xref.")
    parser.add_argument("--nso", type=Path, default=Path("ltd-work/analysis/main.uncompressed"))
    parser.add_argument("--nso-base", type=parse_int, default=NSO_BASE)
    parser.add_argument("--guest-base", type=parse_int, default=GUEST_BASE)
    parser.add_argument("--window", type=int, default=8, help="Max instructions between ADRP and ADD.")
    return run(parser.parse_args())


def run(args: argparse.Namespace) -> int:
    nso = args.nso.read_bytes()
    segments = parse_segments(nso)
    text = segments[0]
    targets: dict[int, str] = {}
    for query in args.strings:
        for file_offset in find_strings(nso, query.encode("utf-8")):
            relative = file_to_relative(segments, file_offset)
            if relative is None:
                continue
            targets[args.nso_base + relative] = query
            print(
                f"string query={query!r} file={file_offset:#x} "
                f"rel={relative:#x} nso={args.nso_base + relative:#x} guest={args.guest_base + relative:#x}"
            )

    if not targets:
        return 1

    active: dict[int, tuple[int, int]] = {}
    text_data = nso[text.file_offset : text.file_offset + text.size]
    for offset in range(0, len(text_data) - 3, 4):
        pc = args.nso_base + text.mem_offset + offset
        insn = struct.unpack_from("<I", text_data, offset)[0]
        adrp = decode_adrp(insn, pc)
        if adrp is not None:
            register, page = adrp
            active[register] = (page, args.window)
            continue

        add = decode_add_imm(insn)
        if add is not None:
            rd, rn, imm = add
            if rn in active:
                page, _ = active[rn]
                target = page + imm
                if target in targets:
                    relative = pc - args.nso_base
                    print(
                        f"xref query={targets[target]!r} at_nso={pc:#x} rel={relative:#x} "
                        f"guest={args.guest_base + relative:#x} target={target:#x} rd=x{rd} rn=x{rn}"
                    )

        expired: list[int] = []
        for register, (page, remaining) in active.items():
            remaining -= 1
            if remaining <= 0:
                expired.append(register)
            else:
                active[register] = (page, remaining)
        for register in expired:
            active.pop(register, None)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

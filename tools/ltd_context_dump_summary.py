#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


REGISTER_RE = re.compile(r"\b(x(?:[0-9]|[12][0-9]|3[01])|sp)=0x([0-9a-fA-F]+)")
DEFAULT_REGISTERS = ["x0", "x1", "x2", "x3", "x8", "x19", "x20", "x21", "x22", "x24", "x29", "x30", "sp"]
GUEST_BASE = 0x8506000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LTD context dump register snapshots.")
    parser.add_argument("dump_dir", type=Path, help="Directory from TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_DIR.")
    parser.add_argument("--guest-base", default=hex(GUEST_BASE), help="Runtime main guest base.")
    parser.add_argument("--registers", default=",".join(DEFAULT_REGISTERS), help="Comma-separated register columns.")
    return parser.parse_args()


def parse_int(value: str) -> int:
    value = value.strip()
    return int(value[2:] if value.lower().startswith("0x") else value, 16)


def parse_registers(text: str) -> dict[str, str]:
    registers: dict[str, str] = {}
    for name, value in REGISTER_RE.findall(text):
        key = "x31" if name == "sp" else name
        registers[key] = f"0x{int(value, 16):x}"
        if name == "sp":
            registers["sp"] = registers[key]
    return registers


def pc_from_name(path: Path) -> int:
    match = re.search(r"-pc-([0-9a-fA-F]+)\.txt$", path.name)
    return int(match.group(1), 16) if match else 0


def main() -> int:
    args = parse_args()
    guest_base = parse_int(args.guest_base)
    columns = [column.strip() for column in args.registers.split(",") if column.strip()]
    print(",".join(["pc", "relative", *columns]))
    for path in sorted(args.dump_dir.glob("context-*-pc-*.txt")):
        pc = pc_from_name(path)
        registers = parse_registers(path.read_text())
        row = [
            f"0x{pc:x}",
            f"0x{pc - guest_base:x}" if pc >= guest_base else "",
            *[registers.get(column, "") for column in columns],
        ]
        print(",".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

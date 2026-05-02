#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path


MANIFEST_RE = re.compile(r"request-(?P<index>[0-9a-fA-F]+)-(?P<phase>[^-]+)-pc-(?P<pc>[0-9a-fA-F]+)\.txt$")
BLOB_RE = re.compile(r"request-(?P<index>[0-9a-fA-F]+)-(?P<phase>[^-]+)-pc-(?P<pc>[0-9a-fA-F]+)-(?P<name>.+)\.bin$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LTD request/voice-context object dumps.")
    parser.add_argument("dump_dir", type=Path, help="Directory from TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_DIR.")
    parser.add_argument("--pointer-low", default="0x6000000000", help="Lower bound for pointer-like values.")
    parser.add_argument("--pointer-high", default="0x7000000000", help="Upper bound for pointer-like values.")
    parser.add_argument("--limit", type=int, default=16, help="Rows per group.")
    return parser.parse_args()


def parse_hex(value: str) -> int:
    value = value.strip()
    return int(value[2:] if value.lower().startswith("0x") else value, 16)


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        key, _, value = line.partition("=")
        if key and value:
            result[key.strip()] = value.strip()
    return result


def words(data: bytes) -> list[int]:
    end = len(data) - (len(data) % 8)
    return [struct.unpack_from("<Q", data, offset)[0] for offset in range(0, end, 8)]


def main() -> int:
    args = parse_args()
    pointer_low = parse_hex(args.pointer_low)
    pointer_high = parse_hex(args.pointer_high)

    manifests: list[tuple[str, str, Path, dict[str, str]]] = []
    blobs: dict[tuple[str, str], list[tuple[str, Path, list[int]]]] = defaultdict(list)

    for path in sorted(args.dump_dir.iterdir()):
        manifest_match = MANIFEST_RE.match(path.name)
        if manifest_match:
            manifests.append(
                (
                    manifest_match.group("index"),
                    manifest_match.group("phase"),
                    path,
                    parse_manifest(path),
                )
            )
            continue

        blob_match = BLOB_RE.match(path.name)
        if blob_match:
            blobs[(blob_match.group("index"), blob_match.group("phase"))].append(
                (
                    blob_match.group("name"),
                    path,
                    words(path.read_bytes()),
                )
            )

    print(f"manifests={len(manifests)} blobs={sum(len(items) for items in blobs.values())}")
    for index, phase, path, manifest in manifests[: args.limit]:
        print(f"\n{path.name}")
        for key in (
            "pc",
            "manager_slot",
            "manager_root",
            "manager_base",
            "global_object",
            "captured_object",
            "captured_wrapper",
            "request_object",
            "voice_context",
            "ready_flag",
            "text_length",
        ):
            print(f"  {key}={manifest.get(key, '')}")

        for name, blob_path, item_words in sorted(blobs.get((index, phase), [])):
            pointer_offsets: list[tuple[int, int]] = []
            small_offsets: list[tuple[int, int]] = []
            repeated = Counter(item_words)

            for word_index, value in enumerate(item_words):
                offset = word_index * 8
                if pointer_low <= value < pointer_high:
                    pointer_offsets.append((offset, value))
                elif value <= 0x100000:
                    small_offsets.append((offset, value))

            print(f"  {name}: bytes={blob_path.stat().st_size}")
            for offset, value in pointer_offsets[: args.limit]:
                print(f"    ptr +{offset:#04x}={value:#x}")
            for offset, value in small_offsets[: min(args.limit, 8)]:
                print(f"    small +{offset:#04x}={value:#x}")
            for value, count in repeated.most_common(4):
                if count > 1 and value != 0:
                    print(f"    repeat count={count:<4} value={value:#x}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Patch a legally dumped Tomodachi Life game for TTSmodachi.

This helper wraps the annoying 3dstool extract and rebuild steps. Magikoopa is
still the patch injector, so the helper either runs a user-provided patch command
or pauses while you open Magikoopa and press Make and Insert.

Input can be a decrypted .cxi, a .app extracted by GodMode9, a .3ds/.cci
cartridge dump, or a decrypted .cia. Wrapped formats are unwrapped to a CXI
automatically (.cia needs ctrtool, everything else only needs 3dstool).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


REGIONS = ("US", "EU", "JP", "KR")
DEFAULT_WORK_DIR = ".rom-patch-work"


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    input_cxi = args.input.resolve()
    region = args.region.upper()
    output_cxi = (args.output or repo_root / "roms" / f"{region}.cxi").resolve()
    work_dir = (args.work_dir or repo_root / DEFAULT_WORK_DIR).resolve()
    patch_source = (args.patch_source or repo_root / "gamePatch").resolve()

    if region not in REGIONS:
        fail(f"Unknown region {region!r}. Use one of: {', '.join(REGIONS)}")
    if not input_cxi.is_file():
        fail(f"Input file does not exist: {input_cxi}")
    if not patch_source.is_dir():
        fail(f"Patch source directory does not exist: {patch_source}")

    three_dstool = resolve_tool(args.three_dstool)
    if three_dstool is None:
        fail("Could not find 3dstool. Pass --three-dstool /path/to/3dstool or put it on PATH.")

    if work_dir.exists() and not args.resume:
        if args.force or work_dir.name in {DEFAULT_WORK_DIR, "rom-patch-work"}:
            shutil.rmtree(work_dir)
        else:
            fail(f"Work directory already exists: {work_dir}. Use --force or --resume.")

    extract_dir = work_dir / "extract"
    exefs_dir = extract_dir / "exefsd"
    patch_dir = work_dir / "gamePatch"

    if not args.resume:
        input_cxi = prepare_input_cxi(three_dstool, args.ctrtool, input_cxi, work_dir)
        extract_cxi(three_dstool, input_cxi, extract_dir, exefs_dir)
        if args.decompress:
            maybe_decompress_code(three_dstool, exefs_dir / "code.bin", args.strict_decompress)
        stage_magikoopa_work(patch_source, patch_dir, exefs_dir / "code.bin", extract_dir / "exheader.bin")

    original_code = patch_dir / "bak" / "code.bin"
    code_before = sha256(original_code if original_code.is_file() else patch_dir / "code.bin")

    if args.prepare_only:
        print()
        print("Prepared Magikoopa work folder:")
        print(f"  {patch_dir}")
        print()
        print("After Magikoopa says All done, run this to finish rebuilding the CXI:")
        print(
            "  "
            + " ".join(
                shlex.quote(part)
                for part in [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--input",
                    str(input_cxi),
                    "--region",
                    region,
                    "--output",
                    str(output_cxi),
                    "--work-dir",
                    str(work_dir),
                    "--resume",
                    "--no-pause",
                ]
            )
        )
        return 0

    run_patch_step(args, patch_dir)

    code_after = sha256(patch_dir / "code.bin")
    if code_before == code_after and not args.allow_unchanged:
        fail(
            "The staged code.bin did not change. Magikoopa probably did not run. "
            "Use --allow-unchanged only if you are sure the file is already patched."
        )

    rebuild_cxi(three_dstool, patch_dir, extract_dir, exefs_dir, output_cxi)
    print()
    print(f"Patched ROM written to: {output_cxi}")
    print("Keep this file out of git. The repo ignores roms/*.cxi for a reason.")

    if not args.keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)
    else:
        print(f"Kept work folder: {work_dir}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch a legally dumped Tomodachi Life CXI for TTSmodachi.",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="Path to your legal dump: .cxi, .app, .3ds/.cci cartridge dump, or decrypted .cia.",
    )
    parser.add_argument("--region", "-r", default="US", help="Output region name: US, EU, JP, or KR. Default: US.")
    parser.add_argument("--output", "-o", type=Path, help="Output CXI path. Default: roms/<REGION>.cxi.")
    parser.add_argument("--work-dir", type=Path, help="Temporary work folder. Default: repo/.rom-patch-work.")
    parser.add_argument("--patch-source", type=Path, help="Patch template folder. Default: repo/gamePatch.")
    parser.add_argument("--three-dstool", default="3dstool", help="3dstool executable path or command name.")
    parser.add_argument("--ctrtool", default="ctrtool", help="ctrtool executable path or command name (only needed for .cia input).")
    parser.add_argument("--magikoopa", help="Optional Magikoopa executable to launch for the patch step.")
    parser.add_argument(
        "--patch-command",
        help="Optional command to run in the staged Magikoopa folder. Use this for custom headless setups.",
    )
    parser.add_argument("--resume", action="store_true", help="Reuse an existing work folder after patching.")
    parser.add_argument("--prepare-only", action="store_true", help="Extract and stage files, then stop.")
    parser.add_argument("--no-pause", action="store_true", help="Do not wait for Enter after launching Magikoopa.")
    parser.add_argument("--keep-work", action="store_true", help="Do not delete the temporary work folder on success.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing work folder.")
    parser.add_argument("--no-decompress", dest="decompress", action="store_false", help="Skip BLZ decompression.")
    parser.add_argument(
        "--strict-decompress",
        action="store_true",
        help="Fail if BLZ decompression fails instead of keeping the original code.bin.",
    )
    parser.add_argument(
        "--allow-unchanged",
        action="store_true",
        help="Allow rebuild even when Magikoopa did not change code.bin.",
    )
    parser.set_defaults(decompress=True)
    return parser.parse_args()


def resolve_tool(tool: str) -> str | None:
    candidate = Path(tool)
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(tool)
    if found:
        return found
    if os.name == "nt" and not tool.lower().endswith(".exe"):
        found = shutil.which(tool + ".exe")
        if found:
            return found
    return None


def run(command: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(shlex.quote(part) for part in command))
    result = subprocess.run(command, cwd=cwd, text=True)
    if check and result.returncode != 0:
        fail(f"Command failed with exit code {result.returncode}: {' '.join(command)}")
    return result


def detect_dump_format(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(0x104)
    if len(header) >= 0x104 and header[0x100:0x104] == b"NCSD":
        return "ncsd"
    if len(header) >= 0x104 and header[0x100:0x104] == b"NCCH":
        return "ncch"
    if header[:4] == b"\x20\x20\x00\x00":
        return "cia"
    return "unknown"


def require_ncch(path: Path, source_kind: str) -> None:
    if detect_dump_format(path) != "ncch":
        fail(
            f"The content extracted from your {source_kind} is not a decrypted CXI. "
            "Your dump is probably still encrypted. Re-dump it decrypted with GodMode9 "
            "(cartridge: NCSD image options > Decrypt & extract; digital: dump the title decrypted)."
        )


def prepare_input_cxi(three_dstool: str, ctrtool: str, input_path: Path, work_dir: Path) -> Path:
    fmt = detect_dump_format(input_path)
    if fmt == "ncch":
        return input_path

    work_dir.mkdir(parents=True, exist_ok=True)
    unwrapped = work_dir / "input.cxi"

    if fmt == "ncsd":
        print(f"{input_path.name} is a .3ds/.cci cartridge dump, extracting partition 0...")
        run(
            [
                three_dstool,
                "-xvtf",
                "cci",
                str(input_path),
                "--partition0",
                str(unwrapped),
            ]
        )
        require_file(unwrapped)
        require_ncch(unwrapped, ".3ds/.cci dump")
        return unwrapped

    if fmt == "cia":
        resolved_ctrtool = resolve_tool(ctrtool)
        if resolved_ctrtool is None:
            fail(
                "Input is a .cia, which needs ctrtool to unwrap. "
                "Pass --ctrtool /path/to/ctrtool or put it on PATH. "
                "Get it from https://github.com/3DSGuy/Project_CTR/releases"
            )
        print(f"{input_path.name} is a .cia, extracting content 0...")
        prefix = work_dir / "cia-content"
        run([resolved_ctrtool, f"--contents={prefix}", str(input_path)])
        candidates = sorted(work_dir.glob("cia-content.0000.*"))
        if not candidates:
            fail("ctrtool did not produce content 0 from the .cia. Is the file a valid CIA?")
        candidates[0].replace(unwrapped)
        for leftover in work_dir.glob("cia-content.*"):
            leftover.unlink()
        require_ncch(unwrapped, ".cia")
        return unwrapped

    fail(
        f"Unrecognized input format: {input_path}. Expected a decrypted .cxi/.app, "
        "a .3ds/.cci cartridge dump, or a decrypted .cia. Encrypted dumps are the "
        "usual cause; decrypt them with GodMode9 on your 3DS first."
    )
    return input_path  # unreachable, keeps type checkers happy


def extract_cxi(three_dstool: str, input_cxi: Path, extract_dir: Path, exefs_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            three_dstool,
            "-xvtf",
            "cxi",
            str(input_cxi),
            "--header",
            "header",
            "--exefs",
            "exefs",
            "--exh",
            "exheader.bin",
            "--logo",
            "logo",
            "--plain",
            "plain",
            "--romfs",
            "romfs",
        ],
        cwd=extract_dir,
    )
    run(
        [
            three_dstool,
            "-xvtf",
            "exefs",
            str(extract_dir / "exefs"),
            "--exefs-dir",
            str(exefs_dir),
            "--header",
            "exfsheader",
        ],
        cwd=extract_dir,
    )
    require_file(exefs_dir / "code.bin")
    require_file(extract_dir / "exheader.bin")
    check_remaster_version(extract_dir / "exheader.bin")


KNOWN_GOOD_REMASTER_VERSION = 0x0002


def check_remaster_version(exheader_bin: Path) -> None:
    with exheader_bin.open("rb") as handle:
        handle.seek(0x0E)
        raw = handle.read(2)
    if len(raw) != 2:
        return
    version = int.from_bytes(raw, "little")
    print(f"Dump remaster version: {version:04x}")
    if version != KNOWN_GOOD_REMASTER_VERSION:
        print()
        print("WARNING: the TTSmodachi patch was built against remaster version "
              f"{KNOWN_GOOD_REMASTER_VERSION:04x} (Rev 1 / 'Rev A' update applied).")
        print("Your dump is a different revision, so the Magikoopa hooks may land at the")
        print("wrong addresses and the renderer can crash or never become ready.")
        print("If that happens, dump the updated (Rev 1) version of the game instead.")
        print()


def maybe_decompress_code(three_dstool: str, code_bin: Path, strict: bool) -> None:
    decompressed = code_bin.with_name("code_unc.bin")
    if decompressed.exists():
        decompressed.unlink()
    result = run(
        [
            three_dstool,
            "-u",
            "--file",
            str(code_bin),
            "--compress-type",
            "blz",
            "--compress-out",
            str(decompressed),
        ],
        check=False,
    )
    if result.returncode == 0 and decompressed.is_file() and decompressed.stat().st_size > 0:
        code_bin.unlink()
        decompressed.rename(code_bin)
        print("decompressed code.bin")
        return
    if decompressed.exists():
        decompressed.unlink()
    if strict:
        fail("3dstool could not decompress code.bin")
    print("code.bin did not decompress cleanly, keeping it as-is")


def stage_magikoopa_work(patch_source: Path, patch_dir: Path, code_bin: Path, exheader_bin: Path) -> None:
    if patch_dir.exists():
        shutil.rmtree(patch_dir)
    shutil.copytree(
        patch_source,
        patch_dir,
        ignore=shutil.ignore_patterns(
            "bak",
            "build",
            "*.d",
            "*.o",
            "*.x",
            "*.elf",
            "*.bin",
            "*.sym",
            "linker.x",
            "newcodeinfo.h",
        ),
    )
    shutil.copy2(code_bin, patch_dir / "code.bin")
    shutil.copy2(exheader_bin, patch_dir / "exheader.bin")
    bak_dir = patch_dir / "bak"
    bak_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(code_bin, bak_dir / "code.bin")
    shutil.copy2(exheader_bin, bak_dir / "exheader.bin")


def run_patch_step(args: argparse.Namespace, patch_dir: Path) -> None:
    require_file(patch_dir / "code.bin")
    require_file(patch_dir / "exheader.bin")

    if args.patch_command:
        command = args.patch_command.format(patchdir=str(patch_dir))
        print("+ " + command)
        result = subprocess.run(command, cwd=patch_dir, shell=True, text=True)
        if result.returncode != 0:
            fail(f"Patch command failed with exit code {result.returncode}")
        return

    if args.magikoopa:
        magikoopa = resolve_tool(args.magikoopa)
        if magikoopa is None:
            fail(f"Could not find Magikoopa: {args.magikoopa}")
        print(f"Launching Magikoopa from: {patch_dir}")
        process = subprocess.Popen([magikoopa], cwd=patch_dir)
        if not args.no_pause:
            print()
            print("In Magikoopa:")
            print("  1. Set the working directory to the folder above if it did not open there.")
            print("  2. Press Make and Insert.")
            print("  3. Wait until it says All done.")
            input("Press Enter here after Magikoopa finished...")
        if process.poll() is None and args.no_pause:
            print("Magikoopa is still running. Continuing because --no-pause was set.")
        return

    if args.no_pause:
        return

    print()
    print("Magikoopa step")
    print("-------------")
    print(f"Open this folder in Magikoopa: {patch_dir}")
    print("Press Make and Insert, wait for All done, then come back here.")
    print()
    input("Press Enter after Magikoopa finished...")


def rebuild_cxi(three_dstool: str, patch_dir: Path, extract_dir: Path, exefs_dir: Path, output_cxi: Path) -> None:
    shutil.copy2(patch_dir / "code.bin", exefs_dir / "code.bin")
    shutil.copy2(patch_dir / "exheader.bin", extract_dir / "exheader.bin")
    output_cxi.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            three_dstool,
            "-cvtf",
            "exefs",
            str(extract_dir / "exefs"),
            "--exefs-dir",
            str(exefs_dir),
            "--header",
            "exfsheader",
        ],
        cwd=extract_dir,
    )
    run(
        [
            three_dstool,
            "-cvtf",
            "cxi",
            str(output_cxi),
            "--header",
            "header",
            "--exefs",
            "exefs",
            "--exh",
            "exheader.bin",
            "--logo",
            "logo",
            "--plain",
            "plain",
            "--romfs",
            "romfs",
            "--not-encrypt",
        ],
        cwd=extract_dir,
    )


def require_file(path: Path) -> None:
    if not path.is_file():
        fail(f"Expected file was not created: {path}")


def sha256(path: Path) -> str:
    require_file(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    raise SystemExit("error: " + message)


if __name__ == "__main__":
    raise SystemExit(main())

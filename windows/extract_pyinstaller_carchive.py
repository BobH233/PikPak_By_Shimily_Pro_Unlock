#!/usr/bin/env python3

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path


MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
COOKIE_FORMAT = ">8sIIII64s"
TOC_HEADER_FORMAT = ">IIIBc"


def parse_cookie(blob: bytes) -> tuple[int, int, int, int, str]:
    cookie_size = struct.calcsize(COOKIE_FORMAT)
    magic_offset = blob.rfind(MAGIC)
    if magic_offset < 0:
        raise ValueError("PyInstaller cookie not found")
    cookie = blob[magic_offset : magic_offset + cookie_size]
    if len(cookie) != cookie_size:
        raise ValueError("Incomplete PyInstaller cookie")
    _magic, pkg_len, toc_offset, toc_len, pyver, pylib = struct.unpack(
        COOKIE_FORMAT, cookie
    )
    pylib_name = pylib.split(b"\0", 1)[0].decode("utf-8", "replace")
    package_start = len(blob) - pkg_len
    return package_start, toc_offset, toc_len, pyver, pylib_name


def parse_toc(blob: bytes, package_start: int, toc_offset: int, toc_len: int) -> list[dict]:
    entries: list[dict] = []
    pos = package_start + toc_offset
    end = pos + toc_len
    header_size = 4 + struct.calcsize(TOC_HEADER_FORMAT)

    while pos < end:
        entry_size = struct.unpack(">i", blob[pos : pos + 4])[0]
        entry_pos, compressed_size, uncompressed_size, compressed_flag, kind = struct.unpack(
            TOC_HEADER_FORMAT, blob[pos + 4 : pos + header_size]
        )
        name_blob = blob[pos + header_size : pos + entry_size]
        name = name_blob.split(b"\0", 1)[0].decode("utf-8", "replace")
        entries.append(
            {
                "name": name,
                "entry_pos": entry_pos,
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "compressed": bool(compressed_flag),
                "type": kind.decode("latin1"),
            }
        )
        pos += entry_size

    if pos != end:
        raise ValueError(f"TOC parse ended at {pos}, expected {end}")

    return entries


def sanitize_member_path(name: str) -> Path:
    cleaned = name.replace("\\", "/").lstrip("/")
    if not cleaned:
        cleaned = "_unnamed"
    parts = []
    for part in cleaned.split("/"):
        if part in {"", ".", ".."}:
            continue
        parts.append(part)
    if not parts:
        return Path("_unnamed")
    return Path(*parts)


def adapt_output_path(entry_type: str, rel_path: Path) -> Path:
    if entry_type in {"m", "s", "M"} and rel_path.suffix != ".pyc":
        return rel_path.with_suffix(".pyc")
    return rel_path


def adapt_payload(entry_type: str, payload: bytes, pyc_magic: bytes) -> bytes:
    if entry_type in {"m", "s", "M"}:
        return pyc_magic + (b"\0" * 12) + payload
    return payload


def detect_pyc_magic(blob: bytes, package_start: int, entries: list[dict]) -> bytes:
    for entry in entries:
        if entry["name"] != "PYZ-00.pyz":
            continue
        start = package_start + entry["entry_pos"]
        end = start + entry["compressed_size"]
        payload = blob[start:end]
        if payload[:4] == b"PYZ\x00" and len(payload) >= 8:
            return payload[4:8]
    # Fallback for Python 3.11, which matches this sample's declared runtime.
    return b"\xa7\x0d\x0d\x0a"


def extract_members(
    blob: bytes, package_start: int, entries: list[dict], output_dir: Path, pyc_magic: bytes
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "entries": [],
    }

    for entry in entries:
        source_start = package_start + entry["entry_pos"]
        source_end = source_start + entry["compressed_size"]
        payload = blob[source_start:source_end]

        if entry["compressed"]:
            payload = zlib.decompress(payload)

        rel_path = adapt_output_path(entry["type"], sanitize_member_path(entry["name"]))
        payload = adapt_payload(entry["type"], payload, pyc_magic)
        dest = output_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

        manifest["entries"].append(
            {
                "name": entry["name"],
                "path": rel_path.as_posix(),
                "type": entry["type"],
                "compressed_size": entry["compressed_size"],
                "uncompressed_size": entry["uncompressed_size"],
            }
        )

    (output_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a PyInstaller CArchive")
    parser.add_argument("input", help="Path to the PyInstaller executable")
    parser.add_argument(
        "-o",
        "--output",
        help="Output directory; defaults to <input stem>_win_carchive",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output) if args.output else Path(f"{input_path.stem}_win_carchive")

    blob = input_path.read_bytes()
    package_start, toc_offset, toc_len, pyver, pylib_name = parse_cookie(blob)
    entries = parse_toc(blob, package_start, toc_offset, toc_len)
    pyc_magic = detect_pyc_magic(blob, package_start, entries)
    extract_members(blob, package_start, entries, output_dir, pyc_magic)

    summary = {
        "input": str(input_path),
        "output": str(output_dir),
        "python_version": pyver,
        "python_dll": pylib_name,
        "package_start": package_start,
        "entry_count": len(entries),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3

import argparse
import struct
import zlib
from pathlib import Path

from extract_pyinstaller_carchive import COOKIE_FORMAT, parse_cookie, parse_toc


TARGET_MEMBER = r"app\view\about_interface.pyd"
TOC_HEADER_FORMAT = ">IIIBc"


def encode_toc_name(name: str) -> bytes:
    raw = name.encode("utf-8") + b"\0"
    entry_size = 18 + len(raw)
    padded_size = (entry_size + 15) & ~15
    return raw + (b"\0" * (padded_size - entry_size))


def build_cookie(pkg_len: int, toc_offset: int, toc_len: int, pyver: int, pylib_name: str) -> bytes:
    pylib_field = pylib_name.encode("utf-8")
    if len(pylib_field) >= 64:
        raise ValueError("Python DLL name is too long for PyInstaller cookie")
    pylib_field = pylib_field + (b"\0" * (64 - len(pylib_field)))
    return struct.pack(COOKIE_FORMAT, b"MEI\x0c\x0b\x0a\x0b\x0e", pkg_len, toc_offset, toc_len, pyver, pylib_field)


def get_stored_payload(blob: bytes, package_start: int, entry: dict) -> bytes:
    start = package_start + entry["entry_pos"]
    end = start + entry["compressed_size"]
    return blob[start:end]


def rebuild_with_replacement(input_exe: Path, replacement_pyd: Path, output_exe: Path) -> None:
    original_blob = input_exe.read_bytes()
    replacement_bytes = replacement_pyd.read_bytes()

    package_start, _toc_offset, _toc_len, pyver, pylib_name = parse_cookie(original_blob)
    entries = parse_toc(original_blob, package_start, _toc_offset, _toc_len)

    stub = original_blob[:package_start]
    package_parts = []
    toc_parts = []
    current_offset = 0
    replaced = False
    target_entry = None

    for entry in entries:
        if entry["name"] == TARGET_MEMBER:
            payload = zlib.compress(replacement_bytes) if entry["compressed"] else replacement_bytes
            stored_payload = payload
            uncompressed_size = len(replacement_bytes)
            replaced = True
            target_entry = entry
        else:
            stored_payload = get_stored_payload(original_blob, package_start, entry)
            uncompressed_size = entry["uncompressed_size"]

        name_blob = encode_toc_name(entry["name"])
        toc_entry_size = 18 + len(name_blob)
        toc_parts.append(
            struct.pack(">i", toc_entry_size)
            + struct.pack(
                TOC_HEADER_FORMAT,
                current_offset,
                len(stored_payload),
                uncompressed_size,
                int(entry["compressed"]),
                entry["type"].encode("latin1"),
            )
            + name_blob
        )
        package_parts.append(stored_payload)
        current_offset += len(stored_payload)

    if not replaced or target_entry is None:
        raise ValueError(f"Target member not found: {TARGET_MEMBER}")

    payload_blob = b"".join(package_parts)
    toc_offset = len(payload_blob)
    toc_blob = b"".join(toc_parts)
    package_blob = payload_blob + toc_blob
    cookie = build_cookie(
        len(package_blob) + struct.calcsize(COOKIE_FORMAT),
        toc_offset,
        len(toc_blob),
        pyver,
        pylib_name,
    )

    output_exe.write_bytes(stub + package_blob + cookie)

    print(
        f"replaced_member={TARGET_MEMBER} "
        f"original_uncompressed={target_entry['uncompressed_size']} "
        f"new_uncompressed={len(replacement_bytes)} "
        f"output={output_exe}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace app/view/about_interface.pyd inside a PyInstaller onefile exe"
    )
    parser.add_argument("input_exe", help="Original PikPak Desktop.exe")
    parser.add_argument("replacement_pyd", help="Patched about_interface.pyd")
    parser.add_argument("-o", "--output", required=True, help="Output exe path")
    args = parser.parse_args()

    rebuild_with_replacement(
        Path(args.input_exe),
        Path(args.replacement_pyd),
        Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

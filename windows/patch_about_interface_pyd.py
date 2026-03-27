#!/usr/bin/env python3

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


PE32_PLUS_MAGIC = 0x20B
TARGET_FUNCTION_VA = 0x180001CA0
PY_TRUE_IAT_VA = 0x1800243A8
EXPECTED_PROLOGUE = bytes.fromhex("4C 8B DC 55 56 41 56 49 8D 6B A1")


@dataclass
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_pointer: int
    raw_size: int

    def contains_rva(self, rva: int) -> bool:
        span = max(self.virtual_size, self.raw_size)
        return self.virtual_address <= rva < self.virtual_address + span

    def rva_to_offset(self, rva: int) -> int:
        if not self.contains_rva(rva):
            raise ValueError(f"RVA 0x{rva:x} is outside section {self.name}")
        delta = rva - self.virtual_address
        if delta >= self.raw_size:
            raise ValueError(
                f"RVA 0x{rva:x} maps past file-backed bytes in section {self.name}"
            )
        return self.raw_pointer + delta


@dataclass
class PEInfo:
    data: bytes
    image_base: int
    sections: list[Section]

    def va_to_offset(self, va: int) -> int:
        rva = va - self.image_base
        for section in self.sections:
            if section.contains_rva(rva):
                return section.rva_to_offset(rva)
        raise ValueError(f"no section covers VA 0x{va:x}")


def parse_pe(path: Path) -> PEInfo:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("not a PE file")

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 0x18 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("invalid PE header")

    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header_offset = pe_offset + 24
    if optional_header_offset + optional_header_size > len(data):
        raise ValueError("truncated optional header")

    magic = struct.unpack_from("<H", data, optional_header_offset)[0]
    if magic != PE32_PLUS_MAGIC:
        raise ValueError("only PE32+ (64-bit) images are supported")

    image_base = struct.unpack_from("<Q", data, optional_header_offset + 24)[0]
    section_table_offset = optional_header_offset + optional_header_size
    sections: list[Section] = []

    for index in range(number_of_sections):
        offset = section_table_offset + index * 40
        if offset + 40 > len(data):
            raise ValueError("truncated section table")
        name = data[offset : offset + 8].rstrip(b"\x00").decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append(
            Section(
                name=name,
                virtual_address=virtual_address,
                virtual_size=virtual_size,
                raw_pointer=raw_pointer,
                raw_size=raw_size,
            )
        )

    return PEInfo(data=data, image_base=image_base, sections=sections)


def build_patch(site_va: int, target_va: int) -> bytes:
    disp = target_va - (site_va + 7)
    if not -(1 << 31) <= disp < (1 << 31):
        raise ValueError("RIP displacement is out of range")
    return b"\x48\x8B\x05" + struct.pack("<i", disp) + b"\x48\xFF\x00\xC3"


def patch_file(input_path: Path, output_path: Path, force: bool) -> None:
    info = parse_pe(input_path)
    patch_offset = info.va_to_offset(TARGET_FUNCTION_VA)
    patch_bytes = build_patch(TARGET_FUNCTION_VA, PY_TRUE_IAT_VA)
    end = patch_offset + len(patch_bytes)

    current = info.data[patch_offset:end]
    if current == patch_bytes:
        raise ValueError("target already appears to be patched")
    if current != EXPECTED_PROLOGUE:
        raise ValueError(
            "unexpected bytes at patch site:\n"
            f"  expected: {EXPECTED_PROLOGUE.hex(' ')}\n"
            f"  actual:   {current.hex(' ')}"
        )

    if output_path.exists() and output_path != input_path and not force:
        raise FileExistsError(f"output exists: {output_path}")

    blob = bytearray(info.data)
    blob[patch_offset:end] = patch_bytes
    output_path.write_bytes(blob)

    print(f"image base:       0x{info.image_base:x}")
    print(f"patch VA:         0x{TARGET_FUNCTION_VA:x}")
    print(f"patch file offset: 0x{patch_offset:x}")
    print(f"original bytes:   {EXPECTED_PROLOGUE.hex(' ')}")
    print(f"patched bytes:    {patch_bytes.hex(' ')}")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Patch about_interface.pyd so sub_180001CA0 immediately returns "
            "Py_True for every normal call that reaches the core checker."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="about_interface.pyd",
        help="path to the original Windows .pyd module",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="path to write the patched file; defaults to <input>.patched",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    return parser


def main() -> int:
    args = build_argparser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(
        input_path.suffix + ".patched"
    )
    patch_file(input_path, output_path, args.force)
    print(f"patched file written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

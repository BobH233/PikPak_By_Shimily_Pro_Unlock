#!/usr/bin/env python3

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
N_TYPE = 0x0E
N_SECT = 0x0E

TARGET_SYMBOL = "___pyx_pw_15about_interface_9MyEncrypt_3checkLicense"
CALLSITE_PATTERN = (
    "E8 ?? ?? ?? ?? 49 89 C7 48 89 85 50 FF FF FF 4D 85 E4 74 0A"
)
PY_TRUE_PATTERN = "4C 8B 35 ?? ?? ?? ?? 49 FF 06"


@dataclass
class Segment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    max_vmaddr: int

    def contains_vmaddr(self, vmaddr: int) -> bool:
        return self.vmaddr <= vmaddr < self.max_vmaddr

    def vmaddr_to_fileoff(self, vmaddr: int) -> int:
        if not self.contains_vmaddr(vmaddr):
            raise ValueError(f"vmaddr 0x{vmaddr:x} is outside segment {self.name}")
        delta = vmaddr - self.vmaddr
        if delta >= self.filesize:
            raise ValueError(
                f"vmaddr 0x{vmaddr:x} maps past file-backed bytes in {self.name}"
            )
        return self.fileoff + delta


@dataclass
class Symbol:
    name: str
    value: int
    sect: int
    n_type: int


@dataclass
class MachOInfo:
    data: bytes
    segments: list[Segment]
    text_segment: Segment
    symbols: list[Symbol]

    def vmaddr_to_fileoff(self, vmaddr: int) -> int:
        for segment in self.segments:
            if segment.contains_vmaddr(vmaddr):
                return segment.vmaddr_to_fileoff(vmaddr)
        raise ValueError(f"no segment covers vmaddr 0x{vmaddr:x}")

    def text_symbols(self) -> list[Symbol]:
        text_vm_start = self.text_segment.vmaddr
        text_vm_end = self.text_segment.vmaddr + self.text_segment.vmsize
        return [
            symbol
            for symbol in self.symbols
            if (symbol.n_type & N_TYPE) == N_SECT
            and text_vm_start <= symbol.value < text_vm_end
        ]


def parse_macho(path: Path) -> MachOInfo:
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError("file too small to be a Mach-O 64-bit image")

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != MH_MAGIC_64:
        raise ValueError("only thin little-endian Mach-O 64-bit images are supported")

    _, _, _, _, ncmds, _, _, _ = struct.unpack_from("<8I", data, 0)
    offset = 32
    segments: list[Segment] = []
    symtab: tuple[int, int, int, int] | None = None

    for _ in range(ncmds):
        if offset + 8 > len(data):
            raise ValueError("truncated load command table")

        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmdsize < 8 or offset + cmdsize > len(data):
            raise ValueError("invalid Mach-O load command size")

        if cmd == LC_SEGMENT_64:
            (
                _,
                _,
                segname_raw,
                vmaddr,
                vmsize,
                fileoff,
                filesize,
                _,
                _,
                _,
                _,
            ) = struct.unpack_from("<II16sQQQQiiII", data, offset)
            segname = segname_raw.rstrip(b"\x00").decode("ascii", errors="replace")
            segments.append(
                Segment(
                    name=segname,
                    vmaddr=vmaddr,
                    vmsize=vmsize,
                    fileoff=fileoff,
                    filesize=filesize,
                    max_vmaddr=vmaddr + vmsize,
                )
            )
        elif cmd == LC_SYMTAB:
            _, _, symoff, nsyms, stroff, strsize = struct.unpack_from(
                "<IIIIII", data, offset
            )
            symtab = (symoff, nsyms, stroff, strsize)

        offset += cmdsize

    if symtab is None:
        raise ValueError("Mach-O has no LC_SYMTAB")

    text_segment = next((segment for segment in segments if segment.name == "__TEXT"), None)
    if text_segment is None:
        raise ValueError("Mach-O has no __TEXT segment")

    symoff, nsyms, stroff, strsize = symtab
    if stroff + strsize > len(data):
        raise ValueError("invalid string table bounds")

    strings = data[stroff : stroff + strsize]
    symbols: list[Symbol] = []
    entry_size = 16

    for index in range(nsyms):
        entry_off = symoff + index * entry_size
        if entry_off + entry_size > len(data):
            raise ValueError("truncated nlist_64 table")
        strx, n_type, sect, _, value = struct.unpack_from("<IBBHQ", data, entry_off)
        if strx >= len(strings):
            name = ""
        else:
            end = strings.find(b"\x00", strx)
            if end == -1:
                end = len(strings)
            name = strings[strx:end].decode("utf-8", errors="replace")
        symbols.append(Symbol(name=name, value=value, sect=sect, n_type=n_type))

    return MachOInfo(data=data, segments=segments, text_segment=text_segment, symbols=symbols)


def parse_pattern(pattern: str) -> list[int | None]:
    parts = pattern.split()
    parsed: list[int | None] = []
    for part in parts:
        if part == "??":
            parsed.append(None)
        else:
            parsed.append(int(part, 16))
    return parsed


def find_pattern(blob: bytes, pattern: list[int | None]) -> int:
    limit = len(blob) - len(pattern) + 1
    for start in range(max(limit, 0)):
        for index, expected in enumerate(pattern):
            if expected is not None and blob[start + index] != expected:
                break
        else:
            return start
    return -1


def find_symbol(info: MachOInfo, symbol_name: str) -> Symbol:
    for symbol in info.symbols:
        if symbol.name == symbol_name:
            return symbol
    raise ValueError(f"symbol not found: {symbol_name}")


def estimate_function_size(info: MachOInfo, symbol: Symbol) -> int:
    text_symbols = sorted(
        (
            candidate
            for candidate in info.text_symbols()
            if candidate.value >= symbol.value and candidate.name
        ),
        key=lambda candidate: candidate.value,
    )
    next_addr = info.text_segment.vmaddr + info.text_segment.vmsize
    for candidate in text_symbols:
        if candidate.value > symbol.value:
            next_addr = candidate.value
            break
    size = next_addr - symbol.value
    if size <= 0:
        raise ValueError(f"failed to estimate size for symbol {symbol.name}")
    return size


def resolve_rip_target(insn_vmaddr: int, disp_offset: int, data: bytes) -> int:
    disp = struct.unpack_from("<i", data, disp_offset)[0]
    return insn_vmaddr + 7 + disp


def build_patch(callsite_vmaddr: int, py_true_ptr_vmaddr: int) -> bytes:
    disp = py_true_ptr_vmaddr - (callsite_vmaddr + 7)
    if not -(1 << 31) <= disp < (1 << 31):
        raise ValueError("RIP displacement for __Py_TrueStruct_ptr is out of range")
    return b"\x4c\x8b\x3d" + struct.pack("<i", disp) + bytes.fromhex(
        "4C 89 BD 50 FF FF FF 90"
    )


def locate_patch(info: MachOInfo) -> tuple[int, bytes, bytes]:
    function_symbol = find_symbol(info, TARGET_SYMBOL)
    function_size = estimate_function_size(info, function_symbol)
    function_fileoff = info.vmaddr_to_fileoff(function_symbol.value)
    function_blob = info.data[function_fileoff : function_fileoff + function_size]

    callsite_pattern = parse_pattern(CALLSITE_PATTERN)
    callsite_offset = find_pattern(function_blob, callsite_pattern)
    if callsite_offset < 0:
        raise ValueError("callsite signature not found inside target function")

    py_true_pattern = parse_pattern(PY_TRUE_PATTERN)
    py_true_offset = find_pattern(function_blob, py_true_pattern)
    if py_true_offset < 0:
        raise ValueError("Py_True load signature not found inside target function")

    callsite_vmaddr = function_symbol.value + callsite_offset
    py_true_insn_vmaddr = function_symbol.value + py_true_offset
    py_true_ptr_vmaddr = resolve_rip_target(py_true_insn_vmaddr, py_true_offset + 3, function_blob)

    patch_bytes = build_patch(callsite_vmaddr, py_true_ptr_vmaddr)
    original_bytes = function_blob[callsite_offset : callsite_offset + len(patch_bytes)]
    patch_fileoff = function_fileoff + callsite_offset
    return patch_fileoff, original_bytes, patch_bytes


def patch_file(input_path: Path, output_path: Path, force: bool) -> None:
    info = parse_macho(input_path)
    patch_offset, original_bytes, patch_bytes = locate_patch(info)
    blob = bytearray(info.data)
    end = patch_offset + len(patch_bytes)

    current = bytes(blob[patch_offset:end])
    if current == patch_bytes:
        raise ValueError("target already appears to be patched")
    if current != original_bytes:
        raise ValueError(
            "unexpected bytes at patch site:\n"
            f"  expected: {original_bytes.hex(' ')}\n"
            f"  actual:   {current.hex(' ')}"
        )

    if output_path.exists() and output_path != input_path and not force:
        raise FileExistsError(f"output exists: {output_path}")

    blob[patch_offset:end] = patch_bytes
    output_path.write_bytes(blob)

    print(f"target symbol: {TARGET_SYMBOL}")
    print(f"patch file offset: 0x{patch_offset:x}")
    print(f"original bytes: {original_bytes.hex(' ')}")
    print(f"patched  bytes: {patch_bytes.hex(' ')}")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Patch about_interface.so by resolving the exported Cython wrapper "
            "symbol and locating the verify-call site with a wildcard signature."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="about_interface.so",
        help="path to the original Mach-O bundle",
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

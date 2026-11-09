#!/usr/bin/env python3
"""Emit the mach-o symbol manifest the asset-free executable links against. Three symbol classes, all
absolute (unslid) — see the design spec. mach-o name = one leading underscore prepended to the ELF name.
  1. data syms  (build_image pass1 global table): segmented addresses (0x0Nxxxxxx) of every asset symbol.
  2. ROM syms   (_<seg>SegmentRomStart/End): VROM byte offsets into the image, from the concat layout.
  3. overlay syms (_ovl_<name>Segment{,Rom}{Start,End} = 0): native overlays have no image location, so
     0 is the resident sentinel — the table's vramStart becomes NULL and the actor/gamestate/effect
     loaders take their existing "already loaded" path (no DMA, no relocation, call the native profile).
  4. VRAM syms  (_<seg>SegmentStart/End): the segment's link address (0x0N000000, or 0 for REL0), which
     code subtracts from a data symbol to get its offset in the segment.
"""
import os, json, sys, glob, subprocess
from spec_parse import parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); EX = ROOT + "/extracted/ntsc-1.0"; OUT = ROOT + "/build-cmake/r64image"

def main():
    gsyms = json.load(open(f"{OUT}/global_syms.json"))
    layout = json.load(open(f"{OUT}/layout.json"))["layout"]
    syms = dict(gsyms)
    segs = parse(ROOT, EX)
    numbers = {s["name"]: s["number"] for s in segs}
    for name, (off, size) in layout.items():
        syms[f"_{name}SegmentRomStart"] = off
        syms[f"_{name}SegmentRomEnd"] = off + size
        vram = (numbers.get(name) or 0) << 24
        syms[f"_{name}SegmentStart"] = vram
        syms[f"_{name}SegmentEnd"] = vram + size
    ovl = [s["name"] for s in segs if s["name"].startswith("ovl_")]
    for name in ovl:
        for suf in ("SegmentStart", "SegmentEnd", "SegmentRomStart", "SegmentRomEnd"):
            syms[f"_{name}{suf}"] = 0

    # Segment-base symbols: code takes &D_0N000000 as the raw segmented address 0x0N000000
    # (SEGMENTED_TO_VIRTUAL resolves it at runtime via gSegments).
    for n in range(16):
        syms[f"D_{(n << 24):08X}"] = n << 24

    # Two-sided inventory: a few segments live in the image AND are compiled into the executable
    # (dmadata, elf_message navi hints). Drop any symbol the executable's own objects already define so
    # the manifest doesn't collide — the executable's real definition is authoritative for those.
    exe_defined = set()
    # Objects to inventory: CMake passes the game OBJECT library's objects as argv; a manual run globs
    # any target's src/ objects. Never the extracted asset objects (those are the image's job).
    objs = sys.argv[1:] or glob.glob(f"{ROOT}/build-cmake/CMakeFiles/**/src/**/*.o", recursive=True)
    for o in objs:
        if os.path.basename(o) == "r64_manifest.s.o":
            continue
        r = subprocess.run(["llvm-nm", "--defined-only", o], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) >= 3:
                exe_defined.add(p[-1])  # mach-o name, leading '_'
    dropped = 0
    with open(f"{ROOT}/build-cmake/r64_manifest.s", "w") as f:
        for n, v in syms.items():
            if f"_{n}" in exe_defined:
                dropped += 1
                continue
            f.write(f".globl _{n}\n.set _{n}, 0x{v & 0xFFFFFFFFFFFFFFFF:016x}\n")
    print(f"  dropped {dropped} manifest syms the executable defines", flush=True)
    print(f"manifest: {len(syms)} symbols ({len(gsyms)} data, {2*len(layout)} rom, {4*len(ovl)} overlay)")

if __name__ == "__main__": main()

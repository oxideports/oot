#!/usr/bin/env python3
"""Two-pass native-image builder (pass 1: compile + link each IMAGE segment at its VMA, collect the
global symbol table). WIP — doesn't stop the whole run on one bad segment."""
import os, re, subprocess, sys, json, shutil
from spec_parse import parse

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); EX=ROOT+"/extracted/ntsc-1.0"; OUT=ROOT+"/build-cmake/r64image"
DEFS=("-DPLATFORM_N64=1 -DPLATFORM_GC=0 -DPLATFORM_IQUE=0 -DOOT_VERSION=NTSC_1_0 -DOOT_REVISION=0 "
      "-DOOT_REGION=REGION_US -DLIBULTRA_VERSION=LIBULTRA_VERSION_I -DLIBULTRA_PATCH=1 -DDEBUG_FEATURES=0 "
      "-DNDEBUG -DF3DEX_GBI_2 -DMML_VERSION=MML_VERSION_OOT -DCOMPILER_GCC -DNON_MATCHING=1 -DAVOID_UB=1 "
      "-DN64_MATCHING_TYPE_WIDTHS "  # keep s32/u32 at 32-bit so asset structs match the game (ultratypes.h)
      "-D_LANGUAGE_C").split()
INC="-Iinclude -Iinclude/libc -Isrc -I. -Iextracted/ntsc-1.0 -Ibuild-cmake".split()
# -fdata-sections puts every data object in its own `.data.<symbol>` section, so the per-segment
# linker script can force the segment's header symbol (named exactly like the segment, e.g.
# spot00_scene / spot00_room_0) to offset 0. Scene_ExecuteCommands / Room_Init read the header from
# the segment start, but clang otherwise orders sub-arrays ahead of it — leaving the header at a
# nonzero offset and the game parsing garbage commands. -fno-zero-initialized-in-bss keeps all-zero
# objects (blank font glyphs, zero spawn lists) in .data at their definition position; the game
# indexes glyph files like kanji/nes_font_static by offset.
FLAGS="-fsigned-char -fno-strict-aliasing -fwrapv -w -O2 -std=gnu11 -fdata-sections -fno-zero-initialized-in-bss".split()

def o_to_c(o):
    # spec .o path -> source .c. Some segment sources are committed in assets/ (textures/text/link
    # objects), others are extracted. Search committed first, then extracted.
    rel = o.replace("build-cmake/", "")           # 'assets/objects/X/Y.o' or 'src/...o'
    if rel.endswith(".o"): rel = rel[:-2] + ".c"
    for cand in (rel, "extracted/ntsc-1.0/" + rel):
        if os.path.exists(ROOT + "/" + cand): return cand
    return None  # not found

def run(cmd): return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)

def gen_msgenc():
    # The *_message_data_static.c segments #include generated encoded-text headers (message_data.enc.*.h),
    # produced by tools/msgenc.py from the message tables. Mirror the OoT Makefile recipe (idempotent).
    td = ROOT + "/build-cmake/assets/text"; os.makedirs(td, exist_ok=True)
    jobs = [  # (out, src, msgenc-args)
        ("message_data.enc.nes.h",       "assets/text/message_data.h",       ["--encoding","utf-8","--charmap","assets/text/charmap.nes.txt"]),
        ("message_data.enc.jpn.h",       "assets/text/message_data.h",       ["--encoding","SHIFT-JIS","--wchar","--charmap","assets/text/charmap.jpn.txt"]),
        ("message_data_staff.enc.nes.h", "assets/text/message_data_staff.h", ["--encoding","utf-8","--charmap","assets/text/charmap.nes.txt"]),
    ]
    for out, src, margs in jobs:
        dst = f"{td}/{out}"
        if os.path.exists(dst): continue
        cpp = run(["clang","-E","-P","-xc","-fno-dollars-in-identifiers"]+DEFS+INC+[src])
        p = subprocess.run(["python3.13", "tools/msgenc.py"]+margs+["-", dst], cwd=ROOT,
                           input=cpp.stdout, capture_output=True, text=True)
        print(f"  msgenc {out}: {'ok' if p.returncode==0 else p.stderr.strip()[:80]}", flush=True)

def main():
    os.makedirs(OUT, exist_ok=True)
    gen_msgenc()
    segs=[s for s in parse(ROOT, EX) if s["kind"]=="IMAGE"]
    print(f"pass1 over {len(segs)} IMAGE segments (numbered + REL0)", flush=True)
    gsyms={}; ok=fail=0; fails=[]
    for i,s in enumerate(segs):
        # numbered segments link at number<<24; REL0 (no number) are relocated-at-0 — link at VMA 0 so
        # internal offsets stay segment-relative (the runtime assigns a segment when it DMAs them).
        name=s["name"]; vma=(s["number"]<<24) if s["number"] is not None else 0
        od=f"{OUT}/{name}"; os.makedirs(od,exist_ok=True)
        objs=[]
        for o in s["objs"]:
            c=o_to_c(o)
            if c is None: fails.append((name,f"no src for {o}")); break
            oo=f"{od}/{os.path.basename(c)}.o"
            if os.path.exists(oo): objs.append(oo); continue   # resume: skip already-compiled
            r=run(["clang","-target","aarch64-linux-gnu","-c"]+DEFS+INC+FLAGS+[c,"-o",oo])
            if r.returncode: fails.append((name,f"compile {c}: {r.stderr.strip().splitlines()[-1][:80]}")); break
            objs.append(oo)
        else:
            # The header symbol shares the segment's name; pull its `.data.<name>` (exact match, so the
            # `.data.<name>_<addr>_*` sub-arrays are excluded) to the front so the header lands at
            # segment offset 0. Segments without such a symbol (objects, code) match nothing here and
            # fall through to the general globs unchanged. pass2 reuses this same seg.ld, so pass1's
            # nm'd addresses and the final layout stay in agreement. Zero-initialised asset data (an
            # all-zero spawn list, the extractor's `*_zeros_*` pads) is real ROM content, so .bss goes
            # inside `seg` and is written to the image as zeros; NOLOAD left it as whatever the heap held.
            ld=f"{od}/seg.ld"; open(ld,"w").write(
                f"SECTIONS {{ seg 0x{vma:08x} : {{ *(.data.{name} .rodata.{name} .sdata.{name}) "
                f"*(.data* .rodata* .sdata*) *(.bss* .sbss* COMMON) }} "
                f"/DISCARD/ : {{ *(.note* .comment .eh_frame*) }} }}")
            elf=f"{od}/{name}.elf"
            r=run(["ld.lld","-T",ld]+objs+["-o",elf])
            if r.returncode:
                # undefined-symbol failures are expected in pass1 (cross-seg) — link with --unresolved-symbols=ignore-all
                r=run(["ld.lld","--unresolved-symbols=ignore-all","-T",ld]+objs+["-o",elf])
            if r.returncode: fails.append((name,f"link: {r.stderr.strip().splitlines()[-1][:80]}")); continue
            nm=run(["llvm-nm","--defined-only",elf]).stdout
            for line in nm.splitlines():
                p=line.split()
                if len(p)==3 and p[1] in "DdRrTtBb": gsyms[p[2]]=int(p[0],16)
            ok+=1
        if i%150==0: print(f"  {i}/{len(segs)}  ok={ok} fail={len(fails)} gsyms={len(gsyms)}",flush=True)
    json.dump(gsyms, open(f"{OUT}/global_syms.json","w"))
    print(f"\nPASS1 DONE: ok={ok} fail={len(fails)} global_syms={len(gsyms)}",flush=True)
    from collections import Counter
    print("fail reasons:", Counter(f[1].split(':')[0] for f in fails).most_common(8))
    for f in fails[:12]: print("  FAIL", f)

if __name__=="__main__": main()

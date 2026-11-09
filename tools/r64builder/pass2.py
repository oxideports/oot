#!/usr/bin/env python3
"""Pass 2 + concat: compute ROM layout (spec order) -> _<name>SegmentRomStart/End VROM symbols; global
table = data syms (segmented) + Rom syms (VROM offsets); relink each segment against the weak-absolute
global object; concatenate blobs at romalign'd offsets -> the image."""
import os, json, subprocess, glob
from spec_parse import parse
ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); EX=ROOT+"/extracted/ntsc-1.0"; OUT=ROOT+"/build-cmake/r64image"
def run(c): return subprocess.run(c, cwd=ROOT, capture_output=True, text=True)

data_syms=json.load(open(f"{OUT}/global_syms.json"))
segs=[s for s in parse(ROOT,EX) if s["kind"]=="IMAGE"]  # numbered + REL0 (both carry _<name>SegmentRom* )
seg_by_name={s["name"]:s for s in segs}

# pass1 links each segment's objects in SPEC ORDER (build_image.py: `for o in s["objs"]`), and those
# nm'd addresses become the manifest the executable links against. pass2 MUST relink in the same
# order or the two disagree: with -fdata-sections + the shared seg.ld, object order determines the
# section order (hence every symbol's address). A `glob.glob(*.o)` here is arbitrary filesystem
# order, which diverges for multi-object segments (gameplay_keep has 125 .o's) and lands symbols like
# gSunDL at addresses the game's DLs don't point to — the runtime resolves them to zero/garbage and
# the render thread walks off into a bad DL. Rebuild the exact spec-ordered .o list pass1 used.
def o_to_c(o):
    rel=o.replace("build-cmake/","")
    if rel.endswith(".o"): rel=rel[:-2]+".c"
    for cand in (rel, "extracted/ntsc-1.0/"+rel):
        if os.path.exists(ROOT+"/"+cand): return cand
    return None

def ordered_objs(name):
    d=f"{OUT}/{name}"; out=[]
    for o in seg_by_name[name]["objs"]:
        c=o_to_c(o)
        if c is None: continue
        oo=f"{d}/{os.path.basename(c)}.o"
        if os.path.exists(oo): out.append(oo)
    return out
# built segments have an ELF from pass1
def size_of(name):
    elf=f"{OUT}/{name}/{name}.elf"
    if not os.path.exists(elf): return None
    run(["llvm-objcopy","-O","binary",elf,f"{OUT}/{name}/{name}.sz.bin"])
    return os.path.getsize(f"{OUT}/{name}/{name}.sz.bin")

# ROM layout in spec order (romalign) -> rom offset per built segment + Rom symbols
rom=0; layout={}; romsyms={}
for s in segs:
    sz=size_of(s["name"])
    if sz is None: continue
    al=max(0x10, s["romalign"]); rom=(rom+al-1)//al*al
    layout[s["name"]]=(rom, sz)
    romsyms[f"_{s['name']}SegmentRomStart"]=rom
    romsyms[f"_{s['name']}SegmentRomEnd"]=rom+sz
    rom+=sz
print(f"laid out {len(layout)} segments, ROM size {rom} (0x{rom:x}); rom syms {len(romsyms)}",flush=True)

# weak-absolute global object = data syms + rom syms
allsyms={**data_syms, **romsyms}
with open(f"{OUT}/global_syms.s","w") as f:
    for n,v in allsyms.items(): f.write(f".weak {n}\n{n} = 0x{v:016x}\n")
run(["clang","-target","aarch64-linux-gnu","-c",f"{OUT}/global_syms.s","-o",f"{OUT}/global_syms.o"])
print(f"global object: {len(allsyms)} weak absolutes",flush=True)

# pass2 relink each built segment, objcopy final blob
clean=undef=0; undef_syms=set()
for name in layout:
    d=f"{OUT}/{name}"; objs=ordered_objs(name)  # spec order — MUST match pass1 (see note above)
    ld=f"{d}/seg.ld"; elf=f"{d}/{name}.final.elf"
    r=run(["ld.lld","-T",ld]+objs+[f"{OUT}/global_syms.o","-o",elf])
    if r.returncode:
        undef+=1
        for m in r.stderr.split("undefined symbol: ")[1:]: undef_syms.add(m.splitlines()[0].strip())
        continue
    clean+=1; run(["llvm-objcopy","-O","binary",elf,f"{d}/{name}.bin"])
print(f"\nPASS2: clean={clean} undef={undef} distinct-undef={len(undef_syms)}",flush=True)
print("sample undef:", sorted(undef_syms)[:10])

# concatenate at layout offsets -> image
img=bytearray(rom)
for name,(off,sz) in layout.items():
    b=f"{OUT}/{name}/{name}.bin"
    if os.path.exists(b):
        data=open(b,"rb").read(); img[off:off+len(data)]=data
open(f"{OUT}/oot.vrom","wb").write(img)
json.dump({"layout":layout,"rom_size":rom}, open(f"{OUT}/layout.json","w"))
print(f"IMAGE written: {OUT}/oot.vrom  ({len(img)} bytes)",flush=True)

# R64NROM container the reality64 loader validates (Rom::from_container, src/ultra/rom.rs): 48-byte LE
# header + the image payload. Fields must match FORMAT_VERSION=1, HEADER_LEN=48, endianness=0,
# pointer_width=8, abi_id=0, flags=0, digest=0.
import struct
hdr = bytearray(48)
hdr[0:8] = b"R64NROM\0"
struct.pack_into("<I", hdr, 8, 1)            # format_version
struct.pack_into("<I", hdr, 12, 48)          # header_len
struct.pack_into("<Q", hdr, 16, 48)          # payload_offset
struct.pack_into("<Q", hdr, 24, len(img))    # vrom_len
struct.pack_into("<I", hdr, 32, 0)           # guest_abi_id
hdr[36] = 0                                  # endianness (host little-endian)
hdr[37] = 8                                  # pointer_width (bytes)
struct.pack_into("<H", hdr, 38, 0)           # flags
# hdr[40:48] = payload digest = 0 (integrity check deferred; loader requires zero)
open(f"{OUT}/oot.r64nrom","wb").write(bytes(hdr) + bytes(img))
print(f"CONTAINER written: {OUT}/oot.r64nrom  ({48+len(img)} bytes)",flush=True)

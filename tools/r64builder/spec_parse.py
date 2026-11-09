#!/usr/bin/env python3
"""Parse OoT's spec into segments (name, number, address, flags, kind, c_files)."""
import re, subprocess, sys, os

DEFS = ("-DPLATFORM_N64=1 -DPLATFORM_GC=0 -DPLATFORM_IQUE=0 -DOOT_VERSION=NTSC_1_0 "
        "-DOOT_REVISION=0 -DOOT_REGION=REGION_US -DLIBULTRA_VERSION=LIBULTRA_VERSION_I "
        "-DLIBULTRA_PATCH=1 -DDEBUG_FEATURES=0 -DNDEBUG -DF3DEX_GBI_2 -DN64_MATCHING_TYPE_WIDTHS").split()

def preprocess(root, extracted):
    out = subprocess.run(["clang","-E","-P","-xc","-I.","-Iinclude"]+DEFS+["spec/spec"],
                         cwd=root, capture_output=True, text=True)
    if out.returncode: sys.exit("cpp spec failed:\n"+out.stderr)
    return out.stdout.replace("$(BUILD_DIR)", "build-cmake")

def classify(name, flags):
    if name in ("makerom","boot","code","buffers","n64ddType","ovl_selector"): return "NATIVE"
    if "OVERLAY" in flags: return "NATIVE"
    if name.startswith("ovl_"): return "NATIVE"
    if name.startswith("audio") or name.startswith("Audio"): return "AUDIO"
    return "IMAGE"

def parse(root, extracted):
    text = preprocess(root, extracted); segs=[]
    for blk in re.findall(r"beginseg(.*?)endseg", text, re.S):
        name = (re.search(r'name\s+"([^"]+)"', blk) or [None,None])[1]
        if not name: continue
        num = re.search(r'\bnumber\s+(\w+)', blk); addr = re.search(r'\baddress\s+(\w+)', blk)
        flags = (re.search(r'flags\s+([^\n]+)', blk) or [None,""])[1]
        objs = re.findall(r'include\s+"([^"]+\.o)"', blk)
        kind = classify(name, flags)
        segs.append(dict(name=name, number=int(num[1],0) if num else None,
                         address=int(addr[1],0) if addr else None, kind=kind,
                         romalign=int((re.search(r'romalign\s+(\w+)',blk) or [0,"0x10"])[1],0),
                         objs=objs))
    return segs

if __name__=="__main__":
    root=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); segs=parse(root, root+"/extracted/ntsc-1.0")
    from collections import Counter
    print("total segments:", len(segs))
    print("by kind:", dict(Counter(s["kind"] for s in segs)))
    img=[s for s in segs if s["kind"]=="IMAGE"]
    print("IMAGE segments:", len(img))
    print("  with number:", len([s for s in img if s["number"] is not None]),
          " address-only:", len([s for s in img if s["number"] is None and s["address"] is not None]),
          " neither(REL0):", len([s for s in img if s["number"] is None and s["address"] is None]))
    print("  sample numbers:", sorted(set(s["number"] for s in img if s["number"] is not None))[:12])
    print("  sample IMAGE:", [(s["name"],s["number"],len(s["objs"])) for s in img[:6]])
    print("  NATIVE sample:", [s["name"] for s in segs if s["kind"]=="NATIVE"][:8])

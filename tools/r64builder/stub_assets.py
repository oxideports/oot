#!/usr/bin/env python3
"""Write zeroed stand-ins for the extracted assets so the port builds without a baserom (CI).
Every name, type, texture size and limb enum comes from the committed assets/xml; all data is zero,
so the executable links but does not run. Usage: stub_assets.py [version] (default ntsc-1.0)."""
import os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # the XML paths in baseroms/<version>/config.yml are relative to the repo
from tools import version_config
from tools.assets.descriptor import base, n64resources as n64, z64resources as z64

VERSION = sys.argv[1] if len(sys.argv) > 1 else "ntsc-1.0"
EX = ROOT / "extracted" / VERSION
if (EX / "baserom").exists():
    sys.exit(f"{EX} holds a real extraction; not overwriting it with stand-ins")

SKELETON = {z64.SkeletonType.NORMAL: "SkeletonHeader", z64.SkeletonType.FLEX: "FlexSkeletonHeader",
            z64.SkeletonType.CURVE: "CurveSkeletonHeader"}
LIMB = {z64.LimbType.STANDARD: "StandardLimb", z64.LimbType.LOD: "LodLimb", z64.LimbType.SKIN: "SkinLimb",
        z64.LimbType.CURVE: "SkelCurveLimb", z64.LimbType.LEGACY: "LegacyLimb"}
TYPE = {"DList": "Gfx {}[]", "Blob": "u8 {}[]", "Mtx": "Mtx {}", "Collision": "CollisionHeader {}",
        "Animation": "AnimationHeader {}", "PlayerAnimation": "LinkAnimationHeader {}",
        "LegacyAnimation": "LegacyAnimationHeader {}", "Cutscene": "CutsceneData {}[]", "Scene": "SceneCmd {}[]",
        "Room": "SceneCmd {}[]", "PathList": "Path {}[]", "CurveAnimation": "CurveAnimationHeader {}"}
ARRAY = {"S16Array": "s16", "Vec3sArray": "Vec3s", "VtxArray": "Vtx"}
INCLUDES = ("ultra64.h", "animation.h", "animation_legacy.h", "bgcheck.h", "curve.h", "cutscene.h", "path.h",
            "player.h", "room.h", "scene.h", "skin.h", "tex_len.h")


def declaration(r, defines):
    """The C declaration the extractor gives a resource, minus storage class."""
    n, kind = r.symbol_name, type(r).__name__.removesuffix("ResourceDesc")
    if isinstance(r, n64.TextureResourceDesc):
        defines += [f"#define {n}_WIDTH {r.width}", f"#define {n}_HEIGHT {r.height}"]
        return f"u64 {n}[]"
    if kind in TYPE:
        return TYPE[kind].format(n)
    if kind in ARRAY:
        return f"{ARRAY[kind]} {n}[{r.count}]"
    if kind == "PlayerAnimationData":
        defines.append(f"#define FRAMECOUNT_{n} {r.frame_count}")
        return f"s16 {n}[FRAMECOUNT_{n} * (PLAYER_LIMB_MAX * 3 + 1)]"
    if kind == "Skeleton":
        return f"{SKELETON[r.type]} {n}"
    if kind == "Limb":
        return f"{LIMB[r.limb_type]} {n}"
    if kind == "LimbTable":
        return f"void* {n}[{r.count}]"
    raise NotImplementedError(f"no stand-in for <{kind}> {n}")


def limb_enums(coll):
    # The extractor orders members by the limb table in the ROM; a compile only needs the names. A limb
    # joins the skeleton whose LimbNone prefix it shares, else the first skeleton after it in the file
    # (limbs precede their limb table and skeleton header).
    file = coll.backing_memory.name.upper()
    skels = [(r.offset, r.limb_enum_name or f"{r.symbol_name}Limb",
              r.limb_enum_none_member_name or f"LIMB_{file}_{r.offset:06X}_NONE",
              r.limb_enum_max_member_name or f"LIMB_{file}_{r.offset:06X}_MAX", [])
             for r in coll.resources if isinstance(r, z64.SkeletonResourceDesc)]
    for r in coll.resources:
        if isinstance(r, z64.LimbResourceDesc) and skels:
            member = r.limb_enum_member_name or f"LIMB_{file}_{r.offset:06X}"
            prefixed = [s for s in skels if member.startswith(s[2].removesuffix("NONE"))]
            after = [s for s in skels if s[0] > r.offset]
            if prefixed:
                owner = max(prefixed, key=lambda s: len(s[2]))
            else:
                owner = min(after, key=lambda s: s[0]) if after else skels[-1]
            owner[4].append(member)
    return ["typedef enum %s {\n    %s\n} %s;" % (e, ",\n    ".join([none, *limbs, mx]), e)
            for _, e, none, mx, limbs in skels]


headers = 0
for pool in base.get_resources_desc(version_config.load_version_config(VERSION)):
    for coll in pool.collections:
        name = coll.backing_memory.name
        d = EX / "assets" / coll.out_path
        d.mkdir(parents=True, exist_ok=True)
        defines = []
        decls = [declaration(r, defines) for r in coll.resources]
        h = [f"#ifndef {name.upper()}_H", f"#define {name.upper()}_H", ""]
        h += [f'#include "{i}"' for i in INCLUDES] + [""] + defines + limb_enums(coll)
        if name.startswith("ovl_") and name != "ovl_file_choose":
            # Overlay assets are file-local: the overlay #includes this .c at its end, so the header's
            # static tentative definitions are the data.
            h += [f"static {s.replace('[]', '[1]')};" for s in decls]
            (d / f"{name}.c").write_text(f'#include "{name}.h"\n')
        else:
            # Definitions for build_image.py, so the manifest lists every asset symbol.
            h += [f"extern {s};" for s in decls]
            (d / f"{name}.c").write_text(f'#include "{name}.h"\n' + "".join(f"{s.replace('[]', '[1]')};\n" for s in decls))
        (d / f"{name}.h").write_text("\n".join(h + ["", "#endif", ""]))
        headers += 1

# Texture, vertex and display-list bodies, and the message tables, are #included inside initializers.
bare = {"text/message_data.h": False, "text/message_data_staff.h": False}
for f in [*Path("src").rglob("*.c"), *Path("assets").rglob("*.c")]:
    for eq, inc in re.findall(r'(=?)\s*#include\s+"((?:assets/\S+\.inc\.c)|(?:text/\S+))"', f.read_text(errors="ignore")):
        bare[inc] = bare.get(inc, False) or bool(eq)
bodies = 0
for inc in sorted(bare):
    p = EX / inc
    if not Path(inc).exists() and not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ 0 }\n" if bare[inc] else "")  # `Mtx x =` with no braces needs a value
        bodies += 1
print(f"stub_assets: {headers} headers, {bodies} empty bodies in {EX.relative_to(ROOT)}")

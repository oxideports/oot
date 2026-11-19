cmake_minimum_required(VERSION 3.16.0 FATAL_ERROR)

# Ocarina of Time (ntsc-1.0, US) on the reality64 runtime — native build of the zeldaret/oot decomp.
# Additive glue: game code + extracted assets stay pristine; this file + reality64 are the bridge.
# M0 goal: configure -> compile -> link against reality64.
project(oot-reality64 VERSION 0.1.0 LANGUAGES C CXX ASM)

if(APPLE)
  enable_language(OBJCXX)
endif()

set(CMAKE_OSX_DEPLOYMENT_TARGET "10.15" CACHE STRING "Minimum OS X deployment version")
set(CMAKE_CXX_STANDARD 20 CACHE STRING "The C++ standard to use")
set(CMAKE_C_STANDARD 11 CACHE STRING "The C standard to use")

set(OOT_VERSION ntsc-1.0)
set(EXTRACTED ${CMAKE_SOURCE_DIR}/extracted/${OOT_VERSION})

if(NOT EXISTS ${EXTRACTED}/assets)
  message(FATAL_ERROR "Extracted assets not found at ${EXTRACTED}. Run the devenv `extract` script first.")
endif()

#==============================================================================#
# OoT ntsc-1.0 (US) compile definitions (mirror the decomp Makefile) + port     #
#==============================================================================#
add_compile_definitions(
    PLATFORM_N64=1 PLATFORM_GC=0 PLATFORM_IQUE=0
    OOT_VERSION=NTSC_1_0 OOT_REVISION=0 OOT_REGION=REGION_US
    LIBULTRA_VERSION=LIBULTRA_VERSION_I LIBULTRA_PATCH=1
    DEBUG_FEATURES=0 NDEBUG
    F3DEX_GBI_2
    MML_VERSION=MML_VERSION_OOT   # audio sequence macro language version
    COMPILER_GCC          # native (non-IDO) compiler path in the decomp headers
    NON_MATCHING=1 AVOID_UB=1
    N64_MATCHING_TYPE_WIDTHS   # keep s32/u32 at the N64's 32-bit width on this LP64 host (ultratypes.h)
    _LANGUAGE_C
    NO_SEGMENTED_MEMORY=1  # reality64 identity/native-pointer model (resident code, host heap) — gates the
                           # N64 boot-memory steps (code-segment DMA, RAM wipe, KSEG0 heap). Same signal
                           # SM64's reality64 build uses; unused elsewhere in the OoT tree.
)

# Host portability (the decomp's non-N64 build relies on these).
if (NOT MSVC)
  add_compile_options($<$<COMPILE_LANGUAGE:C>:-fsigned-char>)
  add_compile_options($<$<COMPILE_LANGUAGE:C>:-fno-strict-aliasing>)
  add_compile_options($<$<COMPILE_LANGUAGE:C>:-fwrapv>)
  # Quiet the expected N64-libc redeclaration noise (size_t=unsigned int vs host builtin).
  add_compile_options($<$<COMPILE_LANGUAGE:C>:-Wno-incompatible-library-redeclaration>)
  add_compile_options($<$<COMPILE_LANGUAGE:C>:-Wno-builtin-requires-header>)
endif()

# NOTE: OoT's include dirs go on the GAME target only (below), not global — OoT's include/libc
# stubs must not leak into reality64cpp and shadow the system libc the reality64 shims rely on.

#==============================================================================#
# Game sources (pristine decomp). Exclusions = things reality64 provides or that     #
# are wrong-platform / guest hardware shadows (see reality64 ROADMAP OoT section).    #
#==============================================================================#
file(GLOB_RECURSE OOT_SRC RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} "src/*.c")
list(FILTER OOT_SRC EXCLUDE REGEX "\\.inc\\.c$")           # data fragments, #included not compiled
# reality64 provides the hardware libultra runtime (os/io/etc.); gu/ is pure matrix+trig math, so compile it
# natively (like SM64 builds its own lib/src/gu) — resolves gu* + the sin/cos tables.
list(FILTER OOT_SRC EXCLUDE REGEX "^src/libultra/(os|io|libc|audio|bb|reg|mgu)/")
# sinf/cosf keep their f64 constants as big-endian {hi, lo} word pairs (gu.h `du`); the host libm
# provides both, as it does for sm64.
list(FILTER OOT_SRC EXCLUDE REGEX "^src/libultra/gu/(sinf|cosf)\\.c$")
list(FILTER OOT_SRC EXCLUDE REGEX "_gc\\.c$")              # GameCube-only variants (we build N64)
list(FILTER OOT_SRC EXCLUDE REGEX "_mq\\.c$")              # Master Quest data (OOT_MQ=0 here; MQ is GameCube-only, not this N64 ntsc-1.0 cart)
list(FILTER OOT_SRC EXCLUDE REGEX "^src/code/fault_gc")    # GC fault handler (+ _drawer); N64 uses fault_n64
list(FILTER OOT_SRC EXCLUDE REGEX "_ique\\.c$")            # iQue-only variants
# Audio-data pipeline deferred (real playback runs through arie later). The audio-table TUs carry the
# _Sequence_* / __Audio*SegmentRom* data references; src/audio/r64_no_audio.c provides empty tables in
# their place so the build links and the audio thread inits in NO_RSP mode.
list(FILTER OOT_SRC EXCLUDE REGEX "^src/audio/tables/sequence_table\\.c$")
list(FILTER OOT_SRC EXCLUDE REGEX "^src/audio/tables/samplebank_table\\.c$")
list(FILTER OOT_SRC EXCLUDE REGEX "^src/audio/tables/soundfont_table\\.c$")
list(FILTER OOT_SRC EXCLUDE REGEX "^src/audio/game/session_init\\.c$")
list(FILTER OOT_SRC EXCLUDE REGEX "^src/n64dd/")           # 64DD disk drive — unsupported
list(FILTER OOT_SRC EXCLUDE REGEX "^src/libgcc/")          # MIPS soft-float libgcc (host provides)
list(FILTER OOT_SRC EXCLUDE REGEX "^src/gcc_fix/")         # MIPS gcc shims (native compiler has these)
list(FILTER OOT_SRC EXCLUDE REGEX "^src/boot/driverominit\\.c$")  # guest osDriveRomInit (reality64 provides)
list(FILTER OOT_SRC EXCLUDE REGEX "^src/boot/cic6105\\.c$")       # N64 IPL/CIC checks (boot HW)
list(FILTER OOT_SRC EXCLUDE REGEX "^src/audio/internal/os\\.c$")  # guest osAiSetNextBuffer + AI MMIO

# Extracted assets: compile the 944 standalone TUs; the ~31k *.inc.c are #included by them.
file(GLOB_RECURSE OOT_ASSETS "${EXTRACTED}/assets/*.c")
list(FILTER OOT_ASSETS EXCLUDE REGEX "\\.inc\\.c$")

# Asset-free executable: game data lives in the host-endian image + mach-o manifest, not the binary.
# The manifest's two-sided inventory must nm the game objects before the link, so the game code is an
# OBJECT library and the executable + manifest are wired below (after the asset-generation rules that the
# image depends on). ${OOT_ASSETS} is intentionally not compiled in.
add_library(oot_game OBJECT ${OOT_SRC})

# OoT's own headers, private to the game objects (kept off reality64cpp — see note above).
target_include_directories(oot_game PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/include/libc
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${EXTRACTED}
    ${CMAKE_CURRENT_BINARY_DIR}
)

#==============================================================================#
# Build-time asset generation (mirrors OoT's Makefile asset rules)             #
#   PNG -> .inc.c (build_from_png), .bin -> .bin.inc.c (bin2c), .jpg (build_jfif)
#   Generated under ${BINARY}/assets/... — already on the game include path, so
#   the game's `#include "assets/.../X.inc.c"` resolves to the generated files.  #
#==============================================================================#
set(BIN2C          ${CMAKE_SOURCE_DIR}/tools/bin2c)
set(BUILD_FROM_PNG ${CMAKE_SOURCE_DIR}/tools/assets/build_from_png/build_from_png)
set(BUILD_JFIF     ${CMAKE_SOURCE_DIR}/tools/assets/build_jfif/build_jfif)
# Texture/TLUT/JPEG data is declared as u32/u64 arrays; the RDP reads it in N64 byte order.
if(CMAKE_C_BYTE_ORDER STREQUAL "LITTLE_ENDIAN")
    set(ASSET_BYTE_ORDER --little-endian)
endif()

add_custom_target(oot_asset_tools
    COMMAND ${CMAKE_C_COMPILER} -O2 -o ${BIN2C} ${CMAKE_SOURCE_DIR}/tools/bin2c.c
    COMMAND make -C ${CMAKE_SOURCE_DIR}/tools/assets/n64texconv CC=${CMAKE_C_COMPILER}
    COMMAND make -C ${CMAKE_SOURCE_DIR}/tools/assets/build_from_png CC=${CMAKE_C_COMPILER}
    COMMAND make -C ${CMAKE_SOURCE_DIR}/tools/assets/build_jfif CC=${CMAKE_C_COMPILER}
    COMMENT "Building OoT asset tools (bin2c, n64texconv, build_from_png, build_jfif)")

set(GEN_ASSETS "")
# PNG -> .inc.c  (build_from_png <png> <outdir>/ <extracted asset dir>/)
file(GLOB_RECURSE _oot_pngs RELATIVE ${EXTRACTED}/assets "${EXTRACTED}/assets/*.png")
foreach(rel ${_oot_pngs})
    get_filename_component(_d ${rel} DIRECTORY)
    string(REGEX REPLACE "\\.png$" ".inc.c" _o ${rel})
    add_custom_command(
        OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/assets/${_o}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/assets/${_d}
        COMMAND ${BUILD_FROM_PNG} ${ASSET_BYTE_ORDER} ${EXTRACTED}/assets/${rel} ${CMAKE_CURRENT_BINARY_DIR}/assets/${_d}/ ${EXTRACTED}/assets/${_d}/
        DEPENDS oot_asset_tools ${EXTRACTED}/assets/${rel}
        VERBATIM)
    list(APPEND GEN_ASSETS ${CMAKE_CURRENT_BINARY_DIR}/assets/${_o})
endforeach()
# .bin -> .bin.inc.c  (bin2c -t 1 <bin> <out>)
file(GLOB_RECURSE _oot_bins RELATIVE ${EXTRACTED}/assets "${EXTRACTED}/assets/*.bin")
foreach(rel ${_oot_bins})
    get_filename_component(_d ${rel} DIRECTORY)
    add_custom_command(
        OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c
        COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/assets/${_d}
        COMMAND ${BIN2C} -t 1 ${EXTRACTED}/assets/${rel} ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c
        DEPENDS oot_asset_tools ${EXTRACTED}/assets/${rel}
        VERBATIM)
    list(APPEND GEN_ASSETS ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c)
endforeach()
# .jpg -> .jpg.inc.c  (build_jfif <jpg> <out>)
file(GLOB_RECURSE _oot_jpgs RELATIVE ${EXTRACTED}/assets "${EXTRACTED}/assets/*.jpg")
foreach(rel ${_oot_jpgs})
    get_filename_component(_d ${rel} DIRECTORY)
    add_custom_command(
        OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c
        COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/assets/${_d}
        COMMAND ${BUILD_JFIF} ${ASSET_BYTE_ORDER} ${EXTRACTED}/assets/${rel} ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c
        DEPENDS oot_asset_tools ${EXTRACTED}/assets/${rel}
        VERBATIM)
    list(APPEND GEN_ASSETS ${CMAKE_CURRENT_BINARY_DIR}/assets/${rel}.inc.c)
endforeach()
add_custom_target(oot_assets DEPENDS ${GEN_ASSETS})
add_dependencies(oot_game oot_assets)

#==============================================================================#
# Asset-free executable: two-phase image + manifest, then link                  #
#   The manifest's two-sided inventory must see the game objects before the      #
#   link, so: oot_game (objects) -> image -> manifest(nm objects) -> executable. #
#==============================================================================#
set(R64_IMG ${CMAKE_CURRENT_BINARY_DIR}/r64image)

# Phase 1: the host-endian image. build_image compiles the asset segments (needs the generated .inc.c)
# and pass2 lays them into oot.vrom + emits the segment symbol table. Re-runs when a generated asset
# changes; `devenv clean` forces a full rebuild. (build_image is resumable — it skips existing objects.)
add_custom_command(
    OUTPUT ${R64_IMG}/oot.vrom ${R64_IMG}/oot.r64nrom ${R64_IMG}/global_syms.json ${R64_IMG}/layout.json
    COMMAND python3.13 build_image.py
    COMMAND python3.13 pass2.py
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}/tools/r64builder
    DEPENDS ${GEN_ASSETS}
    COMMENT "r64builder: host-endian image + R64NROM container (build_image -> pass2)"
    VERBATIM)

# Phase 2: the manifest. gen_manifest nm's the game objects (dropping any symbol the executable itself
# defines — dmadata, elf_message) and reads the image's segment symbol table.
add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/r64_manifest.s
    COMMAND python3.13 ${CMAKE_SOURCE_DIR}/tools/r64builder/gen_manifest.py $<TARGET_OBJECTS:oot_game>
    DEPENDS $<TARGET_OBJECTS:oot_game> ${R64_IMG}/global_syms.json ${R64_IMG}/layout.json
    COMMENT "r64builder: mach-o symbol manifest (two-sided inventory)"
    COMMAND_EXPAND_LISTS VERBATIM)

# The executable: game objects + the generated manifest.
add_executable(oot-${OOT_VERSION} $<TARGET_OBJECTS:oot_game> ${CMAKE_CURRENT_BINARY_DIR}/r64_manifest.s)

# build.c embeds build metadata (per-file defines in the decomp Makefile).
set_source_files_properties(${CMAKE_SOURCE_DIR}/src/boot/build.c PROPERTIES
    COMPILE_DEFINITIONS "BUILD_CREATOR=\"zelda@srd44\";BUILD_DATE=\"98-10-21\";BUILD_TIME=\"04:56:31\"")

# dmadata VROM table: normally generated by mkdmadata from the spec. Real generation is the
# ROM-image builder's job (M1); for the M0 link milestone, an empty table stub lets z_std_dma /
# dmadata compile. (Runtime DMA-by-VROM needs the real table — tracked in reality64 ROADMAP.)
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/dmadata_table_spec.h
    "/* M0 stub — empty dmadata table. Real table = mkdmadata(spec), deferred to the ROM-image builder. */\n")

#==============================================================================#
# reality64 integration (corrosion crate + C libultra/RCP shims)                    #
#==============================================================================#
add_subdirectory(./corrosion)

file(GLOB_RECURSE REALITY64_CPP_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/reality64/cpp/*.c")
list(FILTER REALITY64_CPP_SOURCES EXCLUDE REGEX "reality64/cpp/audio/tests/.*")
list(FILTER REALITY64_CPP_SOURCES EXCLUDE REGEX "reality64/cpp/libultra/tests/.*")
# host_main.c is the process entry (R64RuntimeInit -> install $REALITY64_ROM -> main_func -> event loop);
# OoT supplies main_func -> bootproc in src/r64_native_stubs.c.
add_library(reality64cpp STATIC ${REALITY64_CPP_SOURCES})
# Header separation: reality64cpp sees only reality64's headers (its shims use reality64's own
# libultra/* + reality64/internal.h). The game uses only its own ultra64/* headers and links reality64's
# symbols — so reality64 headers must not be global (they'd collide with OoT's identically-named types).
target_include_directories(reality64cpp PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/reality64/cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/reality64/include)
# reality64 models N64 hardware, where s32/u32 are 32-bit, so no ABI-width shim is needed: the guest
# preserves those 32-bit widths on this LP64 host via -DN64_MATCHING_TYPE_WIDTHS (see the global
# compile definitions above), matching reality64's OSTask/OSMesgQueue layout by construction.
target_link_libraries(oot-${OOT_VERSION} PRIVATE reality64cpp)

corrosion_import_crate(MANIFEST_PATH ${CMAKE_CURRENT_SOURCE_DIR}/reality64/Cargo.toml)
target_link_libraries(oot-${OOT_VERSION} PRIVATE reality64)

if(APPLE)
    target_link_libraries(reality64 INTERFACE "-framework Carbon" "-framework Foundation")
    target_link_libraries(reality64 INTERFACE "-framework CoreFoundation -framework AVFoundation -framework CoreAudio -framework AudioToolbox")
    target_link_libraries(reality64 INTERFACE "-framework Metal -framework QuartzCore")
    target_link_libraries(reality64 INTERFACE "-framework IOKit" "-framework ApplicationServices" "-framework AppKit")
    target_link_libraries(reality64 INTERFACE "-lc++")
elseif(WIN32)
    target_link_libraries(reality64 INTERFACE OpenGL32 D3DCompiler imm32 winmm uxtheme dwmapi)
    if(MINGW)
      target_link_libraries(reality64 INTERFACE "-lstdc++")
    endif()
else()
    find_package(X11 REQUIRED)
    find_package(libUsb REQUIRED)
    find_package(ALSA REQUIRED)
    find_package(Freetype REQUIRED)
    find_package(udev REQUIRED)
    target_link_libraries(reality64 INTERFACE ${ALSA_LIBRARY} ${OPENGL_glx_LIBRARY} ${OPENGL_opengl_LIBRARY})
    target_link_libraries(reality64 INTERFACE ${X11_LIBRARIES} ${UDEV_LIBRARY} ${FREETYPE_LIBRARIES})
    target_link_libraries(reality64 INTERFACE Fontconfig::Fontconfig libUsb::libUsb)
    target_link_libraries(reality64 INTERFACE "-lstdc++ -lm -ldl")
endif()

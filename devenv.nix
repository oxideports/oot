{
  pkgs,
  lib,
  inputs,
  ...
}:
let
  overlays = [ (import inputs.rust-overlay) ];
  system = pkgs.stdenv.system;
  rustPkgs = import inputs.nixpkgs { inherit system overlays; };
  # Use stable Rust toolchain (matches sm64/reality64)
  rust-toolchain = rustPkgs.rust-bin.stable.latest.default.override {
    extensions = [ "rust-src" "rust-analyzer" "clippy" ];
  };
in
{
  packages =
    with pkgs;
    [
      # Build tools
      cmake
      ninja
      pkg-config
      git

      # USB support for libusb
      libusb1

      # Development tools
      lldb

      # Font rendering dependencies
      expat

      # Rust toolchain (reality64 + corrosion)
      rust-toolchain

      # Cross-compilation toolchain for asset building
      pkgsCross.mingw32.stdenv.cc

      # Native-image builder (M1): lld links the ELF-compiled asset segments via a linker script
      # (macOS ld64 can't); llvm provides objcopy/nm. Verified end-to-end (segmented reloc + mach-o
      # absolute symbol manifest, PIE-safe). See docs/superpowers/specs/*native-image-builder*.
      lld
      llvm

      # Python 3.13 for the OoT asset/extraction pipeline. Pinned by exact name because the
      # macOS enterShell prepends Xcode's toolchain, whose python3 is 3.9 — too old (the asset
      # extractor uses PEP-604 `X | Y` unions, needing 3.10+). Scripts invoke `python3.13` directly.
      python313
    ]
    ++ lib.optionals pkgs.stdenv.isDarwin [
      fontconfig
    ]
    ++ lib.optionals pkgs.stdenv.isLinux [
      gcc
      clang
      clang-tools
      glew
      libGL
      libxkbcommon
      wayland
      wayland-protocols
      xorg.libX11
      xorg.libXrandr
      xorg.libXi
      freetype
      fontconfig
      alsa-lib
      pulseaudio
      openssl
      udev
    ];

  env = {
    CMAKE_BUILD_TYPE = "Debug";
  };

  scripts = {
    # OoT asset extraction (pure Python — bypasses the build Makefile's MIPS-toolchain gate, which
    # we never want for a native build). Uses nix python3.13 explicitly (Xcode's python3 is 3.9,
    # too old for the extractor). Override the target with VERSION=... (default ntsc-1.0).
    extract.exec = ''
      set -e
      V="''${VERSION:-ntsc-1.0}"
      BR="baseroms/$V"; EX="extracted/$V"
      echo "OoT extraction for $V ..."
      if [ ! -f "$BR/baserom.z64" ]; then
        echo "Error: $BR/baserom.z64 not found — place the baserom there first."; exit 1
      fi
      # (Re)create the venv if missing or older than 3.10.
      if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
        echo "Creating .venv with python3.13 ..."; rm -rf .venv; python3.13 -m venv .venv
      fi
      .venv/bin/pip install -U -q pip
      .venv/bin/pip install -U -q -r requirements.txt
      PY=.venv/bin/python
      J=$(nproc 2>/dev/null || sysctl -n hw.ncpu)
      # Native asset tools the Python extractor needs (no MIPS toolchain involved):
      #   n64texconv - texture decode (ctypes libn64texconv.so);  sampleconv - audio sample convert.
      echo "Building native asset tools (n64texconv, sampleconv) ..."
      make -C tools/assets/n64texconv CC=clang -j"$J"
      make -C tools/audio/sampleconv CC=clang -j"$J"
      $PY tools/decompress_baserom.py "$V"
      $PY tools/extract_baserom.py "$BR/baserom-decompressed.z64" "$EX/baserom" -v "$V"
      $PY -m tools.assets.extract "$EX/baserom" "$EX" -v "$V" -j"$J"
      $PY tools/extract_incbins.py "$EX/baserom" "$EX/incbin" -v "$V"
      $PY tools/extract_text.py "$EX/baserom" "$EX/text" -v "$V"
      $PY tools/extract_audio.py -b "$EX/baserom" -o "$EX" -v "$V" --read-xml
      echo "Extraction complete: $EX"
    '';

    configure.exec =
      if pkgs.stdenv.isDarwin then ''
        echo "Configuring OoT (native/reality64) build with CMake..."
        cmake -H. -Bbuild-cmake -GNinja -DCMAKE_BUILD_TYPE=Debug \
          -DRust_COMPILER="$(which rustc)" \
          -DRust_CARGO="$(which cargo)" \
          -DCMAKE_C_COMPILER="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang" \
          -DCMAKE_CXX_COMPILER="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang++"
      '' else ''
        echo "Configuring OoT (native/reality64) build with CMake..."
        cmake -H. -Bbuild-cmake -GNinja -DCMAKE_BUILD_TYPE=Debug \
          -DRust_COMPILER="$(which rustc)" \
          -DRust_CARGO="$(which cargo)"
      '';

    build.exec = ''
      echo "Building OoT (native/reality64)..."
      cmake --build build-cmake --config Debug -j$(nproc 2>/dev/null || sysctl -n hw.ncpu)
    '';

    # Native-image builder (tools/r64builder). Compiles the decomp's asset segments into a host-endian
    # ROM image the asset-free executable DMAs from, plus the mach-o symbol manifest it links against.
    image.exec = ''
      echo "Building the host-endian native image (build_image -> pass2)..."
      (cd tools/r64builder && python3.13 build_image.py && python3.13 pass2.py)
      echo "Image: build-cmake/r64image/oot.vrom"
    '';

    # Run AFTER a first compile: the two-sided inventory reads the executable's own src/ objects to
    # avoid colliding with symbols it already defines (dmadata, elf_message).
    manifest.exec = ''
      echo "Generating the mach-o symbol manifest..."
      (cd tools/r64builder && python3.13 gen_manifest.py)
      echo "Manifest: build-cmake/r64_manifest.s"
    '';

    # Run the native/reality64 executable with the cart image installed via $REALITY64_ROM.
    run.exec = ''
      echo "Running OoT (native/reality64)..."
      REALITY64_ROM="$PWD/build-cmake/r64image/oot.r64nrom" ./build-cmake/oot-ntsc-1.0
    '';

    clean.exec = ''
      echo "Cleaning build artifacts..."
      rm -rf build-cmake build
      echo "Clean complete"
    '';
  };

  # On macOS we use Xcode's clang via enterShell PATH override (needed for macOS frameworks)
  languages = lib.optionalAttrs pkgs.stdenv.isLinux {
    c.enable = true;
    cplusplus.enable = true;
  };

  enterShell = lib.optionalString pkgs.stdenv.isDarwin ''
    # Get Xcode path via symlink (bypasses Nix's DEVELOPER_DIR override)
    export DEVELOPER_DIR="$(/usr/bin/readlink /var/db/xcode_select_link)"
    export SDKROOT="$DEVELOPER_DIR/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"

    if [ ! -d "$DEVELOPER_DIR" ]; then
      echo "Warning: Xcode not found at $DEVELOPER_DIR"
      echo "Please install Xcode and run: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
    fi

    # Use Xcode's clang for main compilation (required for macOS frameworks)
    export PATH="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin:$DEVELOPER_DIR/usr/bin:$PATH"

    # Use system xcrun (avoids potential issues with Nix wrappers)
    export PATH="${pkgs.runCommand "xcrun-wrapper" {} "mkdir -p $out/bin && ln -s /usr/bin/xcrun $out/bin/xcrun"}/bin:$PATH"
  '' + ''
    echo "=== OoT (reality64) Build Environment ==="
    echo "Toolchain: cmake $(cmake --version 2>/dev/null | head -1 | awk '{print $3}'), rustc $(rustc --version 2>/dev/null | awk '{print $2}')"
    echo ""
    echo "Commands:"
    echo "  extract    - Extract assets from the baserom (Python pipeline; VERSION=... to override)"
    echo "  image      - Build the host-endian native image (build_image -> pass2 -> oot.vrom)"
    echo "  configure  - CMake configure the native/reality64 build"
    echo "  build      - Build OoT (native/reality64)"
    echo "  manifest   - Generate the mach-o symbol manifest (run after a first compile)"
    echo "  clean      - Remove build artifacts"
    echo ""
    echo "Asset-free build order: extract -> image -> configure -> build -> manifest -> build."
    echo "Canonical bring-up target: ntsc-1.0 (OoT US 1.0) — baserom in baseroms/ntsc-1.0/."
    echo "===================================="
  '';
}

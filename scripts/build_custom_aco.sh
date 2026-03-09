#!/usr/bin/env bash

# build_custom_aco.sh
# Synchronizes the custom ACO compiler layer and builds a custom RADV variant.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d "lib/mesa" ]; then
    echo "Error: Base Mesa repository not found in lib/mesa. Run setup_env.sh first."
    exit 1
fi

echo "[+] Syncing custom compiler layer into Mesa tree..."
rsync -av custom_mesa_layer/ lib/mesa/

INSTALL_PREFIX_CUSTOM="$PROJECT_ROOT/build/install_custom"
mkdir -p "$INSTALL_PREFIX_CUSTOM"

# Ensure we use the python venv for Meson if it exists
if [ -f "build/venv/bin/activate" ]; then
    source build/venv/bin/activate
fi

echo "[+] Configuring Custom Mesa RADV..."
if [ ! -f "build/mesa_custom/build.ninja" ]; then
    meson setup build/mesa_custom lib/mesa \
        --prefix="${INSTALL_PREFIX_CUSTOM}" \
        -Dgallium-drivers= \
        -Dvulkan-drivers=amd \
        -Dbuildtype=debugoptimized \
        -Dllvm=enabled
fi

echo "[+] Compiling and Installing Custom Mesa RADV..."
ninja -C build/mesa_custom install

echo "[+] Custom ACO Compilation Complete!"
echo "Custom RADV ICD is located at: ${INSTALL_PREFIX_CUSTOM}/share/vulkan/icd.d/radeon_icd.x86_64.json"

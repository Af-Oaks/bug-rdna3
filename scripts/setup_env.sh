#!/usr/bin/env bash

# setup_env.sh
# RDNA3 Reverse Engineering Lab Setup
# Installs dependencies, compiles Mesa (RADV), and Fossilize isolated.

set -e

echo "[+] Starting RDNA3 Lab Environment Setup..."

# 1. System Dependencies
echo "[+] Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    build-essential meson ninja-build cmake python3-mako \
    bison flex gettext pkg-config libdrm-dev libvulkan-dev llvm-dev \
    llvm-spirv-18 clang libx11-dev libxext-dev libxfixes-dev libxcb-glx0-dev \
    libxcb-shm0-dev libx11-xcb-dev libxcb-dri2-0-dev libxcb-dri3-dev \
    libxcb-present-dev libxshmfence-dev libxrandr-dev libwayland-dev \
    wayland-protocols libelf-dev zlib1g-dev python3-pip python3-setuptools \
    git pciutils wget jq cmake clang-tools linux-headers-generic \
    glslang-tools spirv-tools

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure local directories exist
mkdir -p lib
mkdir -p build/install
INSTALL_PREFIX="$PROJECT_ROOT/build/install"

echo "[+] Setting up Python virtual environment for latest Meson..."
python3 -m venv build/venv
source build/venv/bin/activate
pip install --upgrade pip
pip install meson mako packaging pyyaml

# 2. Build isolated RADV (Mesa 3D)
echo "[+] Setting up isolated RADV (Mesa 3D)..."
cd lib
if [ ! -d "mesa" ]; then
    git clone https://gitlab.freedesktop.org/mesa/mesa.git
    cd mesa
else
    cd mesa
    git pull
fi

echo "[+] Configuring Mesa RADV via Meson..."
if [ ! -f "../../build/mesa/build.ninja" ]; then
    meson setup ../../build/mesa \
        --prefix="${INSTALL_PREFIX}" \
        -Dgallium-drivers= \
        -Dvulkan-drivers=amd \
        -Dbuildtype=debugoptimized \
        -Dllvm=enabled
fi

echo "[+] Compiling and Installing Mesa RADV..."
ninja -C ../../build/mesa install
cd ../..

# 3. Build Fossilize
echo "[+] Setting up Fossilize..."
cd lib
if [ ! -d "Fossilize" ]; then
    git clone --recursive https://github.com/ValveSoftware/Fossilize.git
    cd Fossilize
else
    cd Fossilize
    git pull
fi

echo "[+] Configuring and Compiling Fossilize..."
cmake -B ../../build/fossilize -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}"
cmake --build ../../build/fossilize -j$(nproc)
cmake --install ../../build/fossilize
cd ../..

echo "[+] Setup Complete!"
echo "RADV ICD is located at: ${INSTALL_PREFIX}/share/vulkan/icd.d/radeon_icd.x86_64.json"
echo "Fossilize binaries are in: ${INSTALL_PREFIX}/bin/"

# 4. Build Custom ACO Variant
echo "[+] Initializing Custom ACO Compiler Variant..."
"${PROJECT_ROOT}/scripts/build_custom_aco.sh"

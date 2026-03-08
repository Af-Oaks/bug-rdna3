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
    llvm-spirv clang libx11-dev libxext-dev libxfixes-dev libxcb-glx0-dev \
    libxcb-shm0-dev libx11-xcb-dev libxcb-dri2-0-dev libxcb-dri3-dev \
    libxcb-present-dev libxshmfence-dev libxrandr-dev libwayland-dev \
    wayland-protocols libelf-dev zlib1g-dev python3-pip python3-setuptools \
    git pciutils wget jq cmake clang-tools linux-headers-generic

# Ensure local directories exist
mkdir -p lib
mkdir -p build/install
INSTALL_PREFIX=$(realpath build/install)

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
meson setup ../../build/mesa \
    --prefix="${INSTALL_PREFIX}" \
    -Dgallium-drivers= \
    -Dvulkan-drivers=amd \
    -Dbuildtype=debugoptimized \
    -Dllvm=enabled || echo "Mesa already configured, proceeding to build..."

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

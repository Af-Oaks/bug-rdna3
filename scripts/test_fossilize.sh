#!/usr/bin/env bash

# test_fossilize.sh
# Uses Fossilize to compile and disassemble shaders for RDNA3 architecture testing.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_PREFIX="${PROJECT_ROOT}/build/install"
FOSSILIZE_DISASM="${INSTALL_PREFIX}/bin/fossilize-disasm"

if [ ! -f "$FOSSILIZE_DISASM" ]; then
    echo "Error: fossilize-disasm not found at $FOSSILIZE_DISASM"
    echo "Did you run ./setup_env.sh and build Fossilize?"
    exit 1
fi

INPUT_SHADER=$1
if [ -z "$INPUT_SHADER" ]; then
    echo "Usage: ./test_fossilize.sh <path_to_shader.comp>"
    exit 1
fi

if [ ! -f "$INPUT_SHADER" ]; then
    echo "Error: Shader file '$INPUT_SHADER' not found."
    exit 1
fi

# Check for glslangValidator
if ! command -v glslangValidator &> /dev/null; then
    echo "Error: glslangValidator not found. Install vulkan-sdk or glslang-tools."
    exit 1
fi

BASENAME=$(basename "$INPUT_SHADER" .comp)
SPV_OUT="${BASENAME}.spv"

echo "[+] Compiling ${INPUT_SHADER} to SPIR-V..."
glslangValidator -V "$INPUT_SHADER" -o "$SPV_OUT"

echo "[+] Creating Fossilize database..."
"${INSTALL_PREFIX}/bin/fossilize-synth" --comp "${SPV_OUT}" --output "${BASENAME}.foz"

echo "[+] Running gpu_test_runner to extract ACO ISA..."
"${PROJECT_ROOT}/scripts/gpu_test_runner.sh" --compiler ACO -- "${INSTALL_PREFIX}/bin/fossilize-replay" "${BASENAME}.foz" > "${BASENAME}_aco.asm" 2>&1

echo "[+] Running gpu_test_runner to extract LLVM ISA..."
"${PROJECT_ROOT}/scripts/gpu_test_runner.sh" --compiler LLVM -- "${INSTALL_PREFIX}/bin/fossilize-replay" "${BASENAME}.foz" > "${BASENAME}_llvm.asm" 2>&1

echo "[+] Test finished. Look at ${BASENAME}_aco.asm and ${BASENAME}_llvm.asm for results."

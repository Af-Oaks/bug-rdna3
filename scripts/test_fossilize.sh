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
DIRNAME=$(dirname "$INPUT_SHADER")
SPV_OUT="${DIRNAME}/${BASENAME}.spv"
FOZ_OUT="${DIRNAME}/${BASENAME}.foz"

echo "[+] Compiling ${INPUT_SHADER} to SPIR-V..."
glslangValidator -V "$INPUT_SHADER" -o "$SPV_OUT"

echo "[+] Creating Fossilize database..."
"${INSTALL_PREFIX}/bin/fossilize-synth" --comp "${SPV_OUT}" --output "${FOZ_OUT}"

echo "[+] Running gpu_test_runner to extract ACO_ORIGINAL ISA..."
"${PROJECT_ROOT}/scripts/gpu_test_runner.sh" --compiler ACO_ORIGINAL -- "${INSTALL_PREFIX}/bin/fossilize-replay" "${FOZ_OUT}" > "${DIRNAME}/${BASENAME}_aco_original.asm" 2>&1

echo "[+] Running gpu_test_runner to extract ACO_CUSTOM ISA..."
if [ -d "${PROJECT_ROOT}/build/install_custom" ]; then
    "${PROJECT_ROOT}/scripts/gpu_test_runner.sh" --compiler ACO_CUSTOM -- "${INSTALL_PREFIX}/bin/fossilize-replay" "${FOZ_OUT}" > "${DIRNAME}/${BASENAME}_aco_custom.asm" 2>&1
else
    echo "Warning: Custom ACO not found at ${PROJECT_ROOT}/build/install_custom. Skipping. Run build_custom_aco.sh."
    touch "${DIRNAME}/${BASENAME}_aco_custom.asm"
fi

echo "[+] Running gpu_test_runner to extract LLVM ISA..."
"${PROJECT_ROOT}/scripts/gpu_test_runner.sh" --compiler LLVM -- "${INSTALL_PREFIX}/bin/fossilize-replay" "${FOZ_OUT}" > "${DIRNAME}/${BASENAME}_llvm.asm" 2>&1

echo "[+] Generating Summary Diff..."
SUMMARY_FILE="${DIRNAME}/${BASENAME}_summary.diff"
echo "=== Compiler Comparison Summary ===" > "$SUMMARY_FILE"
echo "Shader: $INPUT_SHADER" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"
echo "Diff: ACO_ORIGINAL vs ACO_CUSTOM" >> "$SUMMARY_FILE"
diff -u "${DIRNAME}/${BASENAME}_aco_original.asm" "${DIRNAME}/${BASENAME}_aco_custom.asm" >> "$SUMMARY_FILE" || true
echo "" >> "$SUMMARY_FILE"
echo "Diff: ACO_ORIGINAL vs LLVM" >> "$SUMMARY_FILE"
diff -u "${DIRNAME}/${BASENAME}_aco_original.asm" "${DIRNAME}/${BASENAME}_llvm.asm" >> "$SUMMARY_FILE" || true

echo "[+] Test finished. Look at ${DIRNAME} for results and ${BASENAME}_summary.diff."

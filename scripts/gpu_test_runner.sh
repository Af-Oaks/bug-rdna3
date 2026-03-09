#!/usr/bin/env bash

# gpu_test_runner.sh
# Standardized execution of Vulkan workloads on RDNA3 for reverse engineering.

set -e

# Default settings
COMPILER="ACO"
DEBUG_CRASH=false
EXTRA_ENV=""
COMMAND=""

function show_help {
    echo "Usage: ./gpu_test_runner.sh [OPTIONS] -- <command_to_run>"
    echo "Options:"
    echo "  --compiler [ACO|LLVM]      Select the compiler backend (Default: ACO)"
    echo "  --vopd                     Enable VOPD (Dual-Issue) via RADV_PERFTEST"
    echo "  --wave32                   Enable wave32 mode via RADV_PERFTEST"
    echo "  --debug-crash              Enable UMR memory dump on crash"
    echo "  --env 'VAR=VAL'            Inject additional environment variables"
    echo "  --help                     Show this help message"
}

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --compiler) COMPILER="$2"; shift ;;
        --vopd) EXTRA_ENV="${EXTRA_ENV} RADV_PERFTEST=vopd" ;;
        --wave32) EXTRA_ENV="${EXTRA_ENV} RADV_PERFTEST=wave32,cswave32" ;;
        --debug-crash) DEBUG_CRASH=true ;;
        --env) EXTRA_ENV="${EXTRA_ENV} $2"; shift ;;
        --help) show_help; exit 0 ;;
        --) shift; COMMAND="$@"; break ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$COMMAND" ]; then
    echo "Error: No command specified to run."
    show_help
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Locate the custom RADV ICD
INSTALL_PREFIX="$PROJECT_ROOT/build/install"
ICD_FILE=$(find "${INSTALL_PREFIX}/share/vulkan/icd.d" -name "*.json" 2>/dev/null | head -n 1)

if [ -z "$ICD_FILE" ]; then
    echo "Warning: Custom RADV ICD not found in ${INSTALL_PREFIX}. Using system Vulkan."
else
    export VK_ICD_FILENAMES="${ICD_FILE}"
    echo "[*] Using isolated RADV ICD: ${VK_ICD_FILENAMES}"
fi

# Setup compiler variables
export RADV_DEBUG="shaders,hang,nocache"
if [ "$COMPILER" == "LLVM" ]; then
    export RADV_DEBUG="${RADV_DEBUG},llvm"
    echo "[*] Backend: AMD LLVM"
else
    echo "[*] Backend: Valve ACO"
fi

# Inject extra env
if [ -n "$EXTRA_ENV" ]; then
    echo "[*] Extra Env: $EXTRA_ENV"
    eval "export $EXTRA_ENV"
fi

# Logging setup
TIMESTAMP=$(date +"%Y%m%d_%H%M")
RUN_ID=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 4 | head -n 1)
LOG_DIR="logs/run_${TIMESTAMP}_ID${RUN_ID}"
mkdir -p "${LOG_DIR}"

echo "[*] Logging to ${LOG_DIR}"

# Metrics capture (Background)
# We use rocm-smi or amdgpu_top if available. For a generic approach:
{
    while true; do
        date +"%H:%M:%S" >> "${LOG_DIR}/gpu_metrics.log"
        if command -v rocm-smi &> /dev/null; then
            rocm-smi --showuse --showmemuse >> "${LOG_DIR}/gpu_metrics.log"
        else
            cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null >> "${LOG_DIR}/gpu_metrics.log" || echo "VRAM Info Unavailable" >> "${LOG_DIR}/gpu_metrics.log"
        fi
        sleep 1
    done
} &
METRICS_PID=$!

# Run the target command
echo "[*] Executing: $COMMAND"
set +e
eval "$COMMAND" > "${LOG_DIR}/stdout.log" 2> "${LOG_DIR}/stderr.log"
EXIT_CODE=$?
set -e

# Stop metrics capture
kill $METRICS_PID 2>/dev/null || true

if [ $EXIT_CODE -ne 0 ]; then
    echo "[!] Command failed with exit code $EXIT_CODE"
    if [ "$DEBUG_CRASH" = true ]; then
        echo "[!] Initiating UMR crash dump (gfx1101)..."
        if command -v umr &> /dev/null; then
            sudo umr -O bits,halt_waves -wa gfx1101 > "${LOG_DIR}/umr_dump.log" 2>&1
            echo "[*] UMR dump saved to ${LOG_DIR}/umr_dump.log"
        else
            echo "[!] UMR not installed or not in PATH. Cannot capture dump."
        fi
    fi
else
    echo "[*] Command completed successfully."
fi

echo "[*] Test execution finished. Logs available in ${LOG_DIR}/"
exit $EXIT_CODE

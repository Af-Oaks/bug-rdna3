#!/usr/bin/env bash
# One g++ invocation. No CMake, no install step, no intermediate objects kept.
# The only output is shaderlab/harness/tcc-shaderbench, which is gitignored.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

[ -f build/fossilize/libfossilize.a ] || { echo "missing build/fossilize/libfossilize.a — run scripts/setup_env.sh"; exit 1; }

g++ -O2 -std=c++17 -Wall -Wextra -Wno-unused-parameter -Wno-missing-field-initializers \
    -I lib/Fossilize -I lib/Fossilize/cli/volk -I /usr/include \
    -DVK_NO_PROTOTYPES \
    shaderlab/harness/main.cpp shaderlab/harness/harness.cpp \
    lib/Fossilize/cli/volk/volk.c \
    build/fossilize/libfossilize.a build/fossilize/libminiz.a \
    -ldl -lpthread \
    -o shaderlab/harness/tcc-shaderbench
echo "built: shaderlab/harness/tcc-shaderbench"

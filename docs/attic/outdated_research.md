> ⛔ **RETIRED — DO NOT CITE.** Moved to `docs/attic/` on 2026-08-20.
> Checked claims in this file were found wrong. See [attic/README.md](README.md)
> for the specific defects and where the corrected version lives.

---

# Comprehensive Technical Report: AMD RDNA 3 Microarchitecture, Hardware Hazard Management, Compiler Heuristics (ACO vs. LLVM), and Low-Level Profiling Workflows

---

## 1. Executive Summary & Research Scope

Modern high-performance real-time graphics rely on aggressive shader compilation pipelines that bridge high-level shading languages (HLSL/GLSL), intermediate representations (SPIR-V, NIR), and bare-metal Instruction Set Architectures (ISA).

This report synthesizes the microarchitectural evolution of AMD's GPU architectures (GCN through RDNA 1, 2, and 3), focusing on:

1. **The Silicon Paradigm Shift:** The migration of ALU dependency tracking and hazard detection from dynamic silicon scoreboards to static compiler-driven scheduling (`s_delay_alu`).
2. **Microarchitectural Execution Constraints:** Dual-issue Wave32 vector operations (VOPD), register file banking, VGPR/SGPR pressure, and SIMD wave occupancy.
3. **Compiler Backends:** Valve's ACO (Mesa RADV) versus AMD's LLVM backend (AMDVLK / PAL).
4. **Binary Capture & Driver Tooling:** Pipeline State Object (PSO) serialization via Fossilize (`.foz`), API-level capture hurdles within containerized runtimes (Proton/Wine), hardware instruction tracing via SQ Thread Tracing (`RADV_THREAD_TRACE` / RGP), and custom ACO IR instrumentation.

---

## 2. The Silicon Paradigm Shift: Hardware vs. Compiler Responsibilities

```
GCN / RDNA 1 & 2 (Dynamic HW Tracking)         RDNA 3 / GFX11 (Compiler-Driven Hazard Control)
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│        Instruction Fetch             │       │        Instruction Fetch             │
└──────────────────┬───────────────────┘       └──────────────────┬───────────────────┘
                   ▼                                              ▼
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│   HW Scoreboard / Hazard Detector    │       │     Static Compiler Delay Parser     │
│   (Silicon Area & Power Overhead)    │       │        (Decodes s_delay_alu)         │
└──────────────────┬───────────────────┘       └──────────────────┬───────────────────┘
                   ▼                                              ▼
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│   Dynamic Stalling & Wave Switch     │       │ Direct Wavefront Context Switch /    │
│   (Per-Cycle Transistor Evaluation)  │       │ Zero HW Dynamic Scoreboard Overhead  │
└──────────────────┬───────────────────┘       └──────────────────┬───────────────────┘
                   ▼                                              ▼
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│            Execution SIMD            │       │            Execution SIMD            │
└──────────────────────────────────────┘       └──────────────────────────────────────┘

```

### 2.1 The Architectural Evolution (GCN $\rightarrow$ RDNA 1/2 $\rightarrow$ RDNA 3)

* **GCN (Graphics Core Next - Wave64):** Employed a 16-wide SIMD executing a 64-thread wavefront over 4 cycles. Dependency tracking relied heavily on hardware scoreboarding and coarse-grained scalar synchronization (`s_waitcnt`).
* **RDNA 1 & 2 (GFX10/GFX10.3 - Wave32/Wave64):** Redesigned the Compute Unit (CU) into a Dual Compute Unit (WGP - WorkGroup Processor) with native 32-wide SIMDs capable of executing 1 instruction per cycle per SIMD. Hardware scoreboards dynamically tracked Vector ALU (VALU) data dependencies across execution cycles.
* **RDNA 3 (GFX11 - Navi 3x):** AMD restructured the pipeline frontend to maximize ALU density per square millimeter of silicon die area. Dynamic VALU-to-VALU dependency scoreboarding logic was stripped from the execution units.

### 2.2 The Silicon Transistor Trade-off

Dynamic hazard detection logic requires continuous comparators and tracking registers across pipeline stages to detect RAW (Read-After-Write), WAR (Write-After-Read), and WAW (Write-After-Write) hazards.

In RDNA 3, AMD eliminated this hardware complexity to reallocate the transistor budget toward:

* **Dedicated AI Matrix Accelerators:** Native Wave Matrix Multiply Accumulate (WMMA) operations.
* **Dual-Issue SIMD Units (VOPD):** Doubling theoretical FP32/INT32 peak execution per Compute Unit.
* **Larger Caches & Decoupled Clocks:** Expanded Vector General Purpose Register (VGPR) physical files and independent Shader Engine / Frontend clock domains.

### 2.3 The AnandTech & Forum Debates: "Hardware Bug" vs. "Static Architectural Shift"

During the post-launch analysis of RDNA 3, public technical forums (such as AnandTech Forums, Reddit `/r/Amd`, and Beyond3D) debated whether the insertion of `s_delay_alu` was a hardware erratum workaround or an intentional design choice.

```
+----------------------------------------------------------------------------------------------------+
| Architectural Consensus:                                                                          |
| "The offloading of VALU dependency resolution to the shader compiler is NOT an erratum; it is an  |
| explicit microarchitectural paradigm shift analogous to static instruction scheduling in VLIW/    |
| EPIC architectures, while retaining a superscalar, SIMT execution frontend."                       |
+----------------------------------------------------------------------------------------------------+

```

* **The Hardware Stance:** If `s_delay_alu` is entirely omitted by a compiler, the hardware remains **functionally correct**. However, when a RAW dependency hazard occurs, the hardware simply stalls the wavefront in the execution pipeline without issuing any other instructions, idling the SIMD unit.
* **The Compiler Requirement:** Emitting `s_delay_alu` informs the wave sequencer (SQ) of the exact latency distance of an impending dependency. This allows the sequencer to switch execution immediately to an alternate ready Wave32 wavefront rather than stalling the SIMD unit.

### 2.4 Mechanics and Bitfield Encoding of `s_delay_alu`

`s_delay_alu` belongs to the **SOPP (Scalar Operation Programmed)** instruction format. It encodes up to two independent dependency descriptions (`DEP0`, `DEP1`) and a skip counter (`SKIP`) in a single 32-bit instruction word:

$$\text{Bitfield Layout: } \mathbf{ \text{ Opcode (0xbf87)}} \quad \vert{} \quad \mathbf{ \text{ Unused}} \quad \vert{} \quad \mathbf{ \text{ DEP1}} \quad \vert{} \quad \mathbf{[10:7] \text{ SKIP}} \quad \vert{} \quad \mathbf{[6:0] \text{ DEP0}}$$

```
 31             23 22          16 15       11 10        7 6           0
┌─────────────────┬──────────────┬───────────┬───────────┬─────────────┐
│  Opcode (0xbf87)│    Unused    │   DEP1    │   SKIP    │    DEP0     │
│    (9 bits)     │   (7 bits)   │ (5 bits)  │ (4 bits)  │  (7 bits)   │
└─────────────────┴──────────────┴───────────┴───────────┴─────────────┘

```

#### Dependency Codes (`DEP0` / `DEP1`)

| Code Value | Symbolic Name | Meaning / Pipeline Resolution |
| --- | --- | --- |
| `0` | `NO_DEP` | No dependency detected. |
| `1 - 4` | `VALU_DEP_1` .. `VALU_DEP_4` | Dependent on a previous VALU instruction 1 to 4 instructions back. |
| `5 - 7` | `TRANS_DEP_1` .. `TRANS_DEP_3` | Dependent on a transcendental VALU instruction (e.g., `v_sin_f32`, `v_cos_f32`, `v_rcp_f32`). |
| `8` | `SALU_DEP_1` | Dependent on a preceding SALU computation result. |

#### Skip Modifiers (`SKIP`)

| Code Value | Symbolic Name | Meaning |
| --- | --- | --- |
| `0` | `SAME_OP` | Both `DEP0` and `DEP1` apply to the immediate next instruction. |
| `1` | `NEXT` | `DEP0` applies to the next instruction; `DEP1` applies to the instruction after it. |
| `2` | `SKIP_1` | `DEP0` applies to next instruction; `DEP1` applies to the instruction 2 slots ahead. |
| `3` | `SKIP_2` | `DEP0` applies to next instruction; `DEP1` applies to the instruction 3 slots ahead. |

---

## 3. Microarchitectural Execution Context: RDNA 3

### 3.1 Dual-Issue Vector Architecture (VOPD)

RDNA 3 implements **VOPD (Vector Operation Dual)**. Under Wave32 execution, a single SIMD32 can dual-issue two independent math instructions in a single clock cycle, doubling compute density.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VOPD Instruction (64-bit)                       │
├───────────────────────────────────┬────────────────────────────────────┤
│           OpX (32-bit)            │            OpY (32-bit)            │
│   e.g., v_dual_fmac_f32 v0, v2, v4│    e.g., v_dual_mul_f32 v1, v3, v5 │
└───────────────────────────────────┴────────────────────────────────────┘

```

#### VOPD Pairing Rules and Architectural Hazards

1. **Register Port Limitations:** The physical vector register file contains a limited number of read/write ports per bank. An OpX and OpY combination cannot exceed the total read-port budget (maximum 3 distinct VGPR sources across both operations for standard configurations, plus scalar/constant broadcast limitations).
2. **Supported Instruction Combinations:** VOPD is restricted to a specific set of operations:
* `v_fma_f32`, `v_fmac_f32`, `v_mul_f32`, `v_add_f32`, `v_sub_f32`, `v_mov_b32`.


3. **Register Alignment Restrictions:** OpX target and OpY target registers must avoid bank collision rules. Even/odd register assignment rules govern which instructions can successfully pack without causing structural stalls.

### 3.2 Physical Register Allocation and SIMD Occupancy

The primary limiter of thread-level parallelism (TLP) on AMD hardware is register pressure.

#### Register Budgets per RDNA 3 Dual Compute Unit (WGP)

* **Vector Registers (VGPRs):** 1,536 physical 32-bit registers per SIMD32 (totaling 6,144 VGPRs per WGP).
* **Scalar Registers (SGPRs):** 104 user SGPRs per wave allocated from a shared scalar register pool.
* **Local Data Share (LDS):** 128 KB per WGP.

$$\text{SIMD32 Theoretical Wavefront Occupancy} = \min\left(32, \left\lfloor \frac{1536}{\text{Allocated VGPRs}} \right\rfloor, \left\lfloor \frac{1024}{\text{Allocated SGPRs}} \right\rfloor \right)$$

```
VGPR Allocation vs. SIMD32 Active Waves
──────────────────────────────────────────────────────────────────
Allocated VGPRs per Wave32  │ Max Active Waves (Occupancy / 32)
────────────────────────────┼─────────────────────────────────────
32 VGPRs                    │ 32 Waves (100% Max Occupancy)
48 VGPRs                    │ 32 Waves (100% Max Occupancy)
64 VGPRs                    │ 24 Waves (75% Occupancy)
96 VGPRs                    │ 16 Waves (50% Occupancy)
128 VGPRs                   │ 12 Waves (37.5% Occupancy)
256 VGPRs (Max Single Wave) │ 6 Waves  (18.75% Occupancy)
──────────────────────────────────────────────────────────────────

```

---

## 4. Compiler Architectures: Valve ACO vs. AMD LLVM

```
                      Shader High-Level Source (GLSL / HLSL)
                                       │
                                       ▼
                       Vulkan SPIR-V Intermediate Bytecode
                                       │
                   ┌───────────────────┴───────────────────┐
                   ▼                                       ▼
         Mesa RADV Frontend                      AMDVLK / PAL Frontend
                   │                                       │
                   ▼                                       ▼
             NIR Optimizer                           LLVM IR Bridge
                   │                                       │
                   ▼                                       ▼
         Valve ACO Compiler Backend              AMD LLVM GPU Backend
  ┌─────────────────────────────────┐     ┌─────────────────────────────────┐
  │ - Native Single-Pass IR Design  │     │ - Heavy SSA Graph Transformations│
  │ - Optimized for Wave32 Stutter  │     │ - TableGen Pattern Instruction  │
  │ - Rapid Register Allocation     │     │   Matching                      │
  │ - Post-RA s_delay_alu Insertion │     │ - Global Greedy Reg Allocator   │
  │ - Strict VOPD Heuristic Packing │     │ - Deep Scheduling DAG Analysis  │
  └────────────────┬────────────────┘     └────────────────┬────────────────┘
                   │                                       │
                   ▼                                       ▼
          Target Machine Code (RDNA 3 GFX11 / AMD ISA Disassembly)

```

### 4.1 Valve ACO (Mesa RADV)

* **Goal:** Minimize shader compilation times to eliminate in-game stuttering while maintaining high instruction-level parallelism.
* **Pipeline Structure:**
1. `NIR -> ACO IR`: Direct instruction translation avoiding heavy tree-parsing.
2. `Value Numbering & Optimization`: Fast local/global value numbering, algebraic simplifications.
3. `Instruction Scheduling (Pre-RA)`: Optimizes for low register pressure to stay within target occupancy boundaries.
4. `Register Allocation (RA)`: Linear scan register allocation directly aware of Wave32 limits.
5. `SSA Deconstruction`: Translates parallel copies to discrete moves/swaps.
6. `Hazard Resolution (Post-RA)`: Implemented in `aco_insert_NOPs.cpp` and `aco_insert_delay_alu.cpp`. Ingests the final physical register sequence and computes the exact dependency distance between instructions to emit optimal `s_delay_alu` opcodes.
7. `Binary Assembler`: Direct machine code emission.



### 4.2 AMD LLVM Backend (AMDVLK / ROCm)

* **Goal:** Maximize compute throughput and vector optimization for high-density compute tasks.
* **Characteristics:**
* Uses heavy SSA graph optimizations with extensive optimization passes.
* Employs TableGen-driven instruction selection.
* Complex instruction schedulers track Instruction-Level Parallelism (ILP) aggressively, which can increase VGPR lifetimes and register pressure, sometimes reducing wave occupancy in complex fragment or ray-tracing shaders.



---

## 5. Capturing, Filtering, and Profiling Infrastructure

### 5.1 Pipeline Capture Mechanics: Fossilize (`.foz`)

Fossilize acts as an implicit Vulkan API intercept layer (`VK_LAYER_fossilize`). It hooks into:

* `vkCreateGraphicsPipelines`
* `vkCreateComputePipelines`
* `vkCreateRayTracingPipelinesKHR`

When intercepted, Fossilize serializes:

1. All bound SPIR-V modules (Vertex, Fragment, Mesh, Task, Compute).
2. The entire `VkPipelineLayout`, descriptor set layouts, and push constant ranges.
3. Full pipeline state (blend states, rasterization state, vertex input descriptions, render pass layouts).

The resulting `.foz` archive acts as an immutable database of all shaders constructed by the application, which can be recompiled and disassembled offline via `fossilize-replay`.

---

### 5.2 Deterministic $O(1)$ Memory Two-Pass Streaming Extraction

When generating multi-gigabyte compiler disassembly logs (`RADV_DEBUG=shaders,nocache`), in-memory parsers encounter Out-Of-Memory (OOM) failures or regex backtracking limits.

The production-grade Python solution streams the log file across two passes:

* **Pass 1:** Incrementally tracks metrics (`v_dual_`, `s_delay_alu`, VGPRs, SGPRs) to rank pipeline hashes without retaining text payloads in RAM.
* **Pass 2:** Selectively extracts disassembly blocks for only the top-ranked candidates.

```python
#!/usr/bin/env python3
"""
Deterministic Two-Pass Streaming ISA Extractor for AMD RDNA 3 / ACO Disassembly Logs
Extracts top-performing and high-hazard shader blocks with minimal memory footprint.
"""

import re
import json
import random
from pathlib import Path
from typing import Dict, List, Any

def extract_deterministic_shaders(log_path: str, output_json: str, seed: int = 42) -> None:
    log_file = Path(log_path)
    if not log_file.exists():
        raise FileNotFoundError(f"Compiler log target missing: {log_path}")

    re_shader_start = re.compile(r'shader:\s*MESA_SHADER_')
    re_blake3 = re.compile(r'source_blake3:\s*\{(.*?)\}')
    re_vgpr = re.compile(r'vgprs:\s*(\d+)')
    re_sgpr = re.compile(r'sgprs:\s*(\d+)')

    shaders: Dict[str, Dict[str, Any]] = {}
    current_hash = None

    print(f"[*] [Pass 1] Profiling metrics from: {log_path} (Streaming Mode)")
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if re_shader_start.search(line):
                current_hash = None
                continue

            if current_hash is None:
                hash_match = re_blake3.search(line)
                if hash_match:
                    raw_hash = hash_match.group(1)
                    current_hash = raw_hash.replace(', ', '_').replace('0x', '').strip()

                    if current_hash not in shaders:
                        shaders[current_hash] = {
                            "blake3_hash": current_hash,
                            "v_dual_count": 0,
                            "s_delay_alu_count": 0,
                            "vgpr_alloc": 0,
                            "sgpr_alloc": 0
                        }
                continue

            # Fast native substring filters to bypass regex overhead
            if "v_dual_" in line:
                shaders[current_hash]["v_dual_count"] += line.count("v_dual_")
            elif "s_delay_alu" in line:
                shaders[current_hash]["s_delay_alu_count"] += line.count("s_delay_alu")
            elif "VGPRs:" in line:
                m = re_vgpr.search(line)
                if m:
                    shaders[current_hash]["vgpr_alloc"] = int(m.group(1))
            elif "SGPRs:" in line:
                m = re_sgpr.search(line)
                if m:
                    shaders[current_hash]["sgpr_alloc"] = int(m.group(1))

    shader_pool = list(shaders.values())
    print(f"[*] Unique shader modules discovered: {len(shader_pool)}")

    if not shader_pool:
        print("[!] Execution aborted: No valid shader blocks identified.")
        return

    # Categorization and Deterministic Selection
    final_selection_map: Dict[str, str] = {}

    # Category 1: Top 20 s_delay_alu (High Hazard Latency)
    shader_pool.sort(key=lambda x: (-x['s_delay_alu_count'], x['blake3_hash']))
    for s in shader_pool[:20]:
        final_selection_map[s['blake3_hash']] = 'top_s_delay_alu'
    shader_pool = shader_pool[20:]

    # Category 2: Top 20 v_dual_ (High Dual-Issue Density)
    shader_pool.sort(key=lambda x: (-x['v_dual_count'], x['blake3_hash']))
    for s in shader_pool[:20]:
        final_selection_map[s['blake3_hash']] = 'top_v_dual'
    shader_pool = shader_pool[20:]

    # Category 3: 20 Deterministic Baseline Random Samples
    shader_pool.sort(key=lambda x: x['blake3_hash'])
    random.seed(seed)
    sample_size = min(20, len(shader_pool))
    for s in random.sample(shader_pool, sample_size):
        final_selection_map[s['blake3_hash']] = 'random_baseline'

    # Pass 2: Selective Disassembly Capture
    print(f"[*] [Pass 2] Selectively isolating ISA disassembly for {len(final_selection_map)} candidates...")
    
    final_results: Dict[str, Dict[str, Any]] = {
        h: {
            "blake3_hash": h,
            "category": final_selection_map[h],
            "metrics": shaders[h],
            "assembly_snippet": []
        }
        for h in final_selection_map
    }

    current_hash = None
    capture_active = False

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if re_shader_start.search(line):
                capture_active = False
                current_hash = None

            if current_hash is None:
                hash_match = re_blake3.search(line)
                if hash_match:
                    raw_hash = hash_match.group(1)
                    current_hash = raw_hash.replace(', ', '_').replace('0x', '').strip()
                    capture_active = current_hash in final_results
                    if capture_active:
                        final_results[current_hash]["assembly_snippet"].append(line)
                continue

            if capture_active:
                final_results[current_hash]["assembly_snippet"].append(line)

    output_list = []
    for h, data in final_results.items():
        data["assembly_snippet"] = "".join(data["assembly_snippet"]).strip()
        
        # Calculate theoretical Wave32 occupancy
        vgprs = data["metrics"]["vgpr_alloc"]
        sgprs = data["metrics"]["sgpr_alloc"]
        wave_vgpr_limit = 32 if vgprs == 0 else min(32, 1536 // vgprs)
        wave_sgpr_limit = 32 if sgprs == 0 else min(32, 1024 // sgprs)
        data["metrics"]["theoretical_wave32_occupancy"] = min(wave_vgpr_limit, wave_sgpr_limit)
        
        output_list.append(data)

    output_list.sort(key=lambda x: x['blake3_hash'])

    print(f"[*] Serializing structured JSON metrics to: {output_json}")
    with open(output_json, 'w', encoding='utf-8') as out_f:
        json.dump(output_list, out_f, indent=4)
    print("[+] Operation successful.")

if __name__ == "__main__":
    extract_deterministic_shaders(
        log_path="isa_dumps/raw_dump.log",
        output_json="rdna3_deterministic_samples.json",
        seed=42
    )

```

---

### 5.3 The Linux Graphics Stack Sandbox & Proton Execution

When tracing Windows titles running through translation layers (e.g., VKD3D-Proton for D3D12 $\rightarrow$ Vulkan):

```
+----------------------------------------------------------------------------------------------------+
| Proton Pressure-Vessel Container Isolation Model:                                                  |
|                                                                                                    |
| Host OS Linux User Space                                                                           |
|  └── Steam Client Process (32-bit ELF)                                                             |
|       └── Pressure-Vessel Bubblewrap Container (/bwrap sandbox)                                    |
|            ├── 32-bit Wine Server (Requires 32-bit Vulkan Drivers)                                 |
|            └── 64-bit Game Process (Remnant 2 / Cyberpunk 2077)                                    |
|                 └── VKD3D-Proton (Translates D3D12 to Vulkan Commands)                             |
|                      └── Loader searches Container Path, NOT Host /home/...                        |
+----------------------------------------------------------------------------------------------------+

```

#### The Failure Points of API Capture Layers (GFXReconstruct in Proton)

1. **Container Isolation (Pressure-Vessel):** Layers compiled outside the runtime environment are rejected due to path resolution and permissions errors within Bubblewrap namespaces.
2. **Dual-Architecture (ELF32 vs. ELF64) Dependencies:** Steam bootstraps games through 32-bit wrappers. If `VK_INSTANCE_LAYERS` points to a 64-bit capture layer, the 32-bit pre-loader will fail to load the `.so` and abort.
3. **Memory Tracking Collisions:** GFXReconstruct's default page-fault detection (`PROT_NONE` memory traps) conflicts with VKD3D-Proton's host-visible resource allocation model.

---

### 5.4 Bare-Metal Driver Profiling Alternatives

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Vulkan API Command Stream (RADV)                     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│            SQTT (Sequencer Thread Trace) Hardware Engine               │
│            - Non-intrusive, silicon-level execution capture            │
│            - Zero API hook overhead / container bypass                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│        Radeon GPU Profiler (.rgp) / Radeon GPU Analyzer (.csv)         │
│        - Visual wavefront timeline and stall breakdown                 │
│        - Physical occupancy and register allocation analysis           │
└────────────────────────────────────────────────────────────────────────┘

```

#### 1. Hardware SQTT Profiling via RADV (Bypasses Sandbox Entirely)

RADV integrates direct control over the hardware Sequencer Thread Trace (SQTT) engine. This requires no external Vulkan layers:

```bash
# Launch options to capture an exact frame trace via file trigger
RADV_THREAD_TRACE=1000 RADV_THREAD_TRACE_TRIGGER=/tmp/rgp_trigger %command%

```

* **Triggering Execution:** Running `touch /tmp/rgp_trigger` writes an `.rgp` file directly to disk, which can be inspected using **Radeon GPU Profiler (RGP)** to observe active wavefront execution, `s_delay_alu` wait periods, and SIMD stall distributions.

#### 2. Static Architectural Analysis via Radeon GPU Analyzer (RGA)

To evaluate SPIR-V binaries extracted from Fossilize archives without launching the game client:

```bash
rga -s vulkan -c gfx1100 --spv shader_module.spv --isa output.isa --analysis output.csv

```

This generates register usage metrics, scalar/vector memory operation breakdowns, and resource allocations for the targeted RDNA 3 architecture.

---

## 6. Valve ACO Custom Instrumentation

The following implementation demonstrates how to inject custom instrumentation within the ACO backend to evaluate stall behaviors and register pressure.

The instrumentation is placed **Post-RA (Post-Register Allocation)**, ensuring that injected debug instructions do not increase virtual register lifetimes or artificially depress wave occupancy.

### 6.1 C++ Implementation: Post-RA Stall and Trap Pass

```cpp
/*
 * Valve ACO Compiler: Post-RA Custom Instruction & Stall Injector
 * File Target: src/amd/compiler/aco_insert_custom_instrumentation.cpp
 */

#include "aco_builder.h"
#include "aco_ir.h"

namespace aco {

/**
 * @brief Injects deterministic hardware stalls and debug exceptions into ACO IR.
 * 
 * Executed Post-RA immediately prior to binary assembly generation.
 * Modifies instruction stream without perturbing register allocation metrics.
 * 
 * @param program Pointer to the root ACO program context.
 * @param stall_cycles Immediate value representing hardware stall cycles (0 = 1 cycle, 15 = 16 cycles).
 * @param target_opcode The opcode matching target for injection (e.g., aco_opcode::v_fmac_f32).
 */
void inject_custom_hardware_stalls(Program* program, uint16_t stall_cycles, aco_opcode target_opcode) {
    // Traverse the Control Flow Graph (CFG) block by block
    for (Block& block : program->blocks) {
        std::vector<aco_ptr<Instruction>> instrumented_stream;
        instrumented_stream.reserve(block.instructions.size() * 2);

        for (aco_ptr<Instruction>& instr : block.instructions) {
            // Check if the current instruction matches the target pattern
            bool match = (instr->opcode == target_opcode);

            // Move the original instruction into the transformed stream
            instrumented_stream.push_back(std::move(instr));

            if (match) {
                // 1. Instantiate an SOPP instruction for the s_nop stall
                aco_ptr<SOPP_instruction> nop_stall{
                    create_instruction<SOPP_instruction>(
                        aco_opcode::s_nop,
                        Format::SOPP,
                        0, // Zero source operand registers consumed
                        0  // Zero destination definition registers modified
                    )
                };
                
                // Set the immediate field: Cycles = stall_cycles + 1
                nop_stall->imm = stall_cycles & 0x000F;
                nop_stall->block = block.index;
                instrumented_stream.push_back(std::move(nop_stall));

                // 2. Instantiate an SOPP instruction for a hardware debug trap
                Builder bld(program);
                bld.reset(&instrumented_stream);
                
                aco_ptr<SOPP_instruction> debug_trap{
                    create_instruction<SOPP_instruction>(
                        aco_opcode::s_trap,
                        Format::SOPP,
                        0,
                        0
                    )
                };
                debug_trap->imm = 0xCAFE; // Diagnostic payload identifier
                debug_trap->block = block.index;
                instrumented_stream.push_back(std::move(debug_trap));
            }
        }

        // Atomically replace the block instruction stream with the instrumented stream
        block.instructions = std::move(instrumented_stream);
    }
}

} // namespace aco

```

---

## 7. Comparative Metric Matrix: RDNA Architectures

| Architectural Attribute | GCN 5 (Vega / GFX9) | RDNA 2 (Navi 2x / GFX10.3) | RDNA 3 (Navi 3x / GFX11) |
| --- | --- | --- | --- |
| **Native Wavefront Size** | Wave64 | Wave32 (Native) / Wave64 | Wave32 (Native) / Wave64 |
| **ALU Issue Model** | 16-wide SIMD (4 cycles/inst) | 32-wide SIMD (1 cycle/inst) | Dual-Issue VOPD (2 inst/cycle/SIMD) |
| **Hazard Resolution** | Silicon Dynamic Scoreboard | Silicon Dynamic Scoreboard | **Static Compiler (`s_delay_alu`)** |
| **Register File per SIMD** | 256 physical VGPRs | 1024 physical VGPRs | **1536 physical VGPRs** |
| **Instruction Matrix Acceleration** | No (Packed Math FP16 only) | No | **Native WMMA Instructions** |
| **Compiler Optimization Target** | Vector packing & unrolling | Instruction Level Parallelism | **VOPD Packing & Hazard Distance** |

---

## 8. Summary of Methodological Framework

```
                       Production Application (UE5 / REDengine)
                                          │
                                          ▼
                      Fossilize Serialization Layer (VK_LAYER)
                                          │
                                          ▼
                         Master Pipeline Database (.foz)
                                          │
                                          ▼
                  Offline Driver Disassembly (RADV_DEBUG=shaders)
                                          │
                                          ▼
                    2-Pass Memory-Safe Extraction Script (extract.py)
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   ▼                                             ▼
       Top 20 s_delay_alu Shaders                     Top 20 v_dual_ Shaders
       (Severe Dependency Stalls)                     (Dual-Issue Math Density)
                   │                                             │
                   └──────────────────────┬──────────────────────┘
                                          │
                                          ▼
                 Targeted Benchmarking & Architectural Validation
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
   Valve ACO Modifications       Radeon GPU Profiler (RGP)     RGA Static Analysis
(Custom Pass / Hazard Delays)    (Live Hardware Wave Traces)  (Live Register Occupancy)

```

This experimental and analytical pipeline provides a reproducible, hardware-aware method for evaluating compiler efficiency, microarchitectural hazards, and instruction scheduling across modern AMD GPU architectures.
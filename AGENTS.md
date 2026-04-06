# Project Context

This repository is a thesis workspace for investigating why RDNA3 shows very different gains across games and workloads relative to RDNA2-era expectations, with emphasis on Linux, Proton, Vulkan, RADV, and ACO behavior.
The goal of this project is to investigate, isolate, and work around potential physical bugs and design limitations in the RDNA3 architecture (specifically the AMD Radeon RX 7800 XT GPU - Navi 32 matrix, ISA GFX1101) running in a Linux environment. The central focus is on the discrepancy between theoretical (TFLOPS) and actual throughput, suspected to be caused by hardware scheduling and instruction issuing failures.

Microarchitectural Hypotheses to be Tested:

The s_delay_alu Danger: The RDNA3 hardware scheduler appears unable to efficiently track data dependencies in the new dual-issue pipeline, forcing compilers (Mesa ACO and AMD LLVM) to aggressively insert software stall cycles (s_delay_alu). We want to modify the compiler to remove these protections and observe wave hangs and corruptions.

VOPD (Dual-Issue) Weakness: The ability to execute two VALU instructions simultaneously (Wave32) requires near-perfect conditions (absence of VGPR bank conflicts). We want to force compilation with and without VOPD to measure the actual penalty.

Memory Violations (MEMVIOL): Handling OOB (Out-of-Bounds) accesses in GFX11 causes severe segmentation faults (VM Faults) that require a GPU reset (amdgpu.gpu_recovery=1).


## Framing

- Do not frame the project as proving an architectural flaw.
- The correct framing is: investigate which workload, pipeline, shader, compiler, and runtime characteristics correlate with high gains versus low gains on RDNA3.
- The workflow must support side-by-side comparison of high-gain and low-gain titles.

## Current Structure

- `analysis/` is the thesis-facing workflow area.
- `analysis/games/<game>/sessions/<session_id>/` is the canonical location for all per-scene evidence.
- `scripts/analysis_pipeline/` contains the Track A / Track B / Track C orchestration scripts.
- `custom_mesa_layer/`, `scripts/build_custom_aco.sh`, `scripts/test_fossilize.sh`, `src/`, and related assets remain relevant for compiler experiments and should not be treated as obsolete.

## Workflow Rules

- Track A is RenderDoc-first for real frame capture.
- Track B is `.foz` mining for pipeline and shader objects from the same scene/session context as Track A.
- Track C correlates Track A, Track B, and optional ISA / RGA / profiling / compiler artifacts.
- Every artifact must remain traceable through `session_id`, checksums, provenance, and manifest files.
- Prefer local repo-managed tools first, vendored tools second, and system tools only when necessary.
- Be explicit about uncertainty. If a match is only heuristic, label it `weak` or `unresolved`.

## Non-Goals

- Do not make `gfxreconstruct` the primary workflow.
- Do not claim `.foz` can reconstruct full scene state.
- Do not pretend exact pipeline matching exists without evidence.
- Do not add cloud services or external databases.

## Existing Useful Assets

- `extract.py` is a legacy helper for mining shader-related signals from compiler/ISA logs. Wrap it when useful; do not make it the core pipeline.
- `src/shaders/remnant2/steamapp_pipeline_cache.foz` and `src/test_vopd/test_vopd.foz` are useful local examples for validating Fossilize-based mining.
- `radeon_gpu_analyzer/` and `build/install/bin/fossilize-*` are local tool sources for optional integration.
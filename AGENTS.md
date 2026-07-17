# Project Context

This repository is a thesis (TCC) workspace investigating why AMD RDNA3 shows very different
gen-over-gen gains across games and workloads relative to RDNA2-era expectations.
Hardware target: AMD Radeon RX 7800 XT — Navi 32 — **ISA target `gfx1101`**
(NOT gfx1100; that is Navi 31). Stack: Ubuntu 24.04 + Steam/Proton + Vulkan + Mesa RADV/ACO,
with two local Mesa builds: stock (`build/install`) and custom ACO (`build/install_custom`,
built from the `custom_mesa_layer/` overlay — currently unmodified, so both compilers are
byte-identical until the first real ACO experiment lands).

Microarchitectural hypotheses under investigation (as measurable correlations, not verdicts):

- **s_delay_alu cost**: RDNA3 moved data-hazard handling from hardware interlocks to
  compiler-inserted `s_delay_alu`; measure its density and theoretical stall impact.
- **VOPD (dual-issue) underuse**: `v_dual_*` requires near-perfect operand/bank conditions;
  measure how often ACO actually emits it and what forcing it on/off changes.
- **VGPR pressure / occupancy**: register pressure vs waves-per-SIMD limits.

## Framing (unchanged, important)

- Do NOT frame the project as proving an architectural flaw.
- Correct framing: investigate which workload, pipeline, shader, compiler, and runtime
  characteristics correlate with high gains versus low gains on RDNA3.
- The workflow must support side-by-side comparison of high-gain and low-gain titles and
  baseline vs modified ACO.

## Current Structure (post-rework, branch `rework`)

- `src/tcc/` — the single Python package; CLI entry point `tcc` (installed in `build/venv`,
  run as `./build/venv/bin/tcc`). Everything flows through it.
- `config/` — tracked TOML configs: `tcc.toml` (global), `games/*.toml` (the game matrix),
  `profiles/*.toml` (experiment variants: driver ICD, RADV flags, capture layers, mangohud).
- `bin/tcc-launch.sh` — Steam `%command%` wrapper (Phase 3; reads `~/.tcc/armed.env`).
- `shaderlab/` — authored GLSL experiments + C++ Vulkan dispatch harness (Phase 5).
- `data/` — gitignored: sessions, foz caches, shaderlab outputs, archived legacy dumps.
- `custom_mesa_layer/` + `scripts/{setup_env,build_custom_aco}.sh` — the ACO experiment area.
- `docs/` — PLAN.md (approved rework plan), THESIS_NOTES.md, later SETUP/WORKFLOWS/GAMES.
- `_attic/` — frozen legacy code (old Track A/B/C pipeline, prototypes). Reference only;
  never import from it at runtime.
- **`TODO.md` at the repo root is the live status tracker — read it first in any new session.**

## Workflow Rules

- Everything is session-scoped: `tcc session new --game X --scene Y` → all artifacts land in
  `data/sessions/<game>/<session_id>/` with manifests, sha256 provenance, and step records.
- Launch experiments via the armed-profile pattern: `tcc arm --profile <name>` then launch;
  never edit Steam launch options per-experiment (they are set once to the wrapper).
- Mining is stats-first: `fossilize-replay --enable-pipeline-stats` gives per-stage
  VGPRs/SGPRs/spills/code-size/waves **plus ACO extras (VOPD, VALU/SALU/VMEM/SMEM counts,
  Latency, Pre-Sched pressure)** keyed by exact pipeline hash. Parse ISA text only for
  ranked top-N offenders via `fossilize-disasm --target isa`.
- Scene scoping via foz delta: snapshot cache before/after, delta the hash sets,
  `fossilize-prune` a scene-scoped sub-database. Remember: foz records pipeline *creation*,
  not draws — RenderDoc frames are the on-screen ground truth.
- A/B comparisons (stock vs custom ACO) must always run with `RADV_DEBUG=nocache` and an
  isolated `MESA_SHADER_CACHE_DIR` (enforced centrally in `tcc.config.profile_env`).
- Be explicit about uncertainty; heuristic linkage must be labeled, never implied as exact.

## Non-Goals / Hard Lessons

- Do NOT reintroduce GFXReconstruct or hand-inject native Vulkan layers into Proton
  (32-bit pre-loader ELF panics, VKD3D allocator collisions, Pressure Vessel path blocks).
  Use `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` — Valve ships container-paired layers.
- Do NOT parse multi-GB `RADV_DEBUG=shaders` dumps again; the driver reports the stats.
- Do NOT claim `.foz` reconstructs scene state or that a mined pipeline was drawn in a frame
  without RenderDoc/manual evidence.
- Do NOT glob `*.foz` for Steam caches — the files have no extension
  (`steamapps/shadercache/<appid>/fozpipelinesv6/steamapprun_pipeline_cache.<hex>`).
- Do NOT put automation state in `/tmp` for Proton games — Pressure Vessel only reliably
  shares `$HOME` (armed profile lives in `~/.tcc/`).
- Do NOT add cloud services or external databases.

## Useful Assets

- `data/foz/remnant2/steamapp_pipeline_cache.foz` — 129MB real Remnant II cache; validated:
  17,730 stat rows extracted under the stock local Mesa build.
- `data/archive/` — legacy 2.1GB ISA dump + 280MB extracted samples (historical only).
- Fossilize CLIs in `build/install/bin/`; RGA arrives as a prebuilt tarball in `tools/rga/`.
- RDNA2/RDNA3 ISA reference PDFs in `pdf_context/`.

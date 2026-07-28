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

- `src/` — the Python source root, split into **contextual top-level packages** (there is no
  umbrella `tcc` package; it was removed 2026-07-28). CLI entry point `tcc` is `src/cli.py`,
  installed in `build/venv`, run as `./build/venv/bin/tcc`.
  - `core/` — config, paths, session, provenance, util, toolchain discovery, `schemas/`
  - `shader_extractor/` — `foz.py`: snapshot / delta / prune / extract from Steam caches
  - `analysis/` — `stats.py`, `mine.py` (later `compare.py`, `isa.py`, `hazards.py`)
  - `benchmark/` — `game_bench.py` (later `shaderbench.py`, `ledger.py`)
  - `launcher/` — `arm.py`, `steam.py` (the armed-profile launch path)
  New modules go in the package that owns the concept; do not create an umbrella package.
- `config/` — tracked TOML configs: `tcc.toml` (global), `games/*.toml` (the game matrix),
  `profiles/*.toml` (experiment variants: driver ICD, RADV flags, capture layers, mangohud).
- `bin/tcc-launch.sh` — Steam `%command%` wrapper (Phase 3; reads `~/.tcc/armed.env`).
- `shaderlab/` — authored GLSL experiments + C++ Vulkan dispatch harness (Phase 5).
- `data/` — gitignored: sessions, foz caches, shaderlab outputs, archived legacy dumps.
- `custom_mesa_layer/` + `scripts/{setup_env,build_custom_aco}.sh` — the ACO experiment area.
- `docs/` — PLAN.md (approved rework plan), THESIS_NOTES.md, later SETUP/WORKFLOWS/GAMES.
- `_attic/` — **deleted 2026-07-28** and gitignored. The `stall_ratio`/`vopd_ratio` formulas
  needed for `analysis/isa.py` and the hazard DAG for `analysis/hazards.py` are recoverable
  from git history: `git show a7f0d75:_attic/prototypes/triage.py` (and `hazards.py`).
  `hazards.py` used `networkx`, which is no longer a declared dependency — re-add it if that
  port happens.
- **`ONGOING.md` at the repo root is the live working context — read it FIRST in any new
  session, and update it after every prompt (see "ONGOING.md protocol" below).**
- **`TODO.md`** is the phase/task tracker (what is done vs left); read it right after ONGOING.md.
- `docs/METRICS_PLAN.md` — Metrics 1 & 2 (static compiler stats + runtime FPS, calibration bridge).
- `docs/SHADERBENCH_PLAN.md` — Metric 3 (execute shaders extracted from game `.foz` files as a
  deterministic workload) + the corpus and ledger design.

## ONGOING.md protocol (mandatory)

`ONGOING.md` is written **for the human to read between sessions**, not for the agent. It is
the answer to "what were we doing, what runs next, what am I supposed to see, what's still
unknown". Treat keeping it current as part of the task, not an optional extra.

**After every prompt** — before ending the turn — update `ONGOING.md` so it reflects reality
at that moment:

- Bump the `Last updated` date and the branch/commit line.
- **Where we stopped**: what was just done and what it proved (with the concrete numbers or
  file paths that back it — a claim without evidence does not go in).
- **Immediate next step**: the single next command or task, with **what result is expected
  and why that result matters**. If it is blocked, name the blocker.
- **Built vs missing**: keep the table honest; move rows the moment status changes, and flag
  tested-but-uncommitted work explicitly.
- **Open questions**: anything unverified, contradictory, or awaiting a decision — including
  questions raised *for* the human. Delete them once answered; do not let them rot.
- **Waiting on a human**: the checklist of things only the human can do (Steam launch
  options, installs, downloads, purchases).
- **Where this is going**: keep the arc paragraph accurate so every next step has a "why".

Rules: no invented results — if something was not run, say "not run". Distinguish
*implemented* from *tested on the GPU* from *committed*. Keep it under ~150 lines by deleting
resolved items rather than appending forever; durable facts graduate to `TODO.md`
("Standing facts") or the relevant `docs/` file. `ONGOING.md` is the *now*, `TODO.md` is the
*plan*, `docs/` is the *method*.
EXTRA RULES: Let it been an summary of the last 1 
EXTRA RULES: Let it been an summary of the last 1 to 5 prompts so its more a summary checkup, STICT UNDER 150 lines, do not over extend, its to be a
HUMAN readable summary and where to look the details.

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
- Do NOT resolve Steam caches by globbing `~/.local/share/Steam` — games live across several
  library folders and the shadercache sits in the game's OWN library; always go through
  `steam.library_folders()` / `steam.shadercache_foz()`. Both layouts must be handled: new
  `fozpipelinesv6/steam_pipeline_cache.foz` (**with** the extension) and legacy
  `steamapprun_pipeline_cache.<hex>/steamapp_pipeline_cache.foz`. The glob
  `**/*pipeline_cache*` (files only) covers both and excludes `replay_cache.*`.
- Do NOT treat every new hash in a foz delta as "created by this run" — Steam can download
  its community pre-cache mid-session. Use `delta.json → run_created` (steamapprun_* only).
- Do NOT put automation state in `/tmp` for Proton games — Pressure Vessel only reliably
  shares `$HOME` (armed profile lives in `~/.tcc/`).
- Do NOT add cloud services or external databases.

## Useful Assets

- `data/foz/remnant2/steamapp_pipeline_cache.foz` — 129MB real Remnant II cache; validated:
  17,730 stat rows extracted under the stock local Mesa build.
- `data/archive/` — legacy 2.1GB ISA dump + 280MB extracted samples (historical only).
- Fossilize CLIs in `build/install/bin/`; RGA arrives as a prebuilt tarball in `tools/rga/`.
- RDNA2/RDNA3 ISA reference PDFs in `pdf_context/`.

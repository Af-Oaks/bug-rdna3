# Domain — what is measured, how, and what the words mean

The mechanism, end to end. Per-package detail is in `src/**/CONTEXT.md`; project
rules are in [REPOCONTEXT.md](REPOCONTEXT.md); live status is
[ONGOING.md](ONGOING.md); the work queue is [TODO.md](TODO.md).

## Framing

Investigate which workload, pipeline, shader, compiler and runtime
characteristics correlate with **high versus low gen-over-gen gains on RDNA3**.
Never frame it as proving an architectural flaw.

- Hardware: RX 7800 XT = Navi 32 = **gfx1101**. (gfx1100 is Navi 31 — wrong chip.)
- Stack: Linux + Steam/Proton + Vulkan + Mesa RADV + ACO. DX12 titles run through
  vkd3d-proton and still produce Vulkan pipelines Fossilize records.
- Comparison axes: high-gain vs low-gain titles; stock ACO vs modified ACO;
  synthetic vs real scenes.

## Three measurements, one ledger

| | measures | deterministic | needs game |
|---|---|---|---|
| **M1 static** | what the compiler emitted (VGPR, VOPD, occupancy) | yes | no |
| **M3 shaderbench** | what that code costs the GPU | yes | no |
| **M2 game FPS** | what the player sees | no | yes |

The **ledger** is one row per (workload × compiler revision). Change the
compiler, re-run, read across: did a static win become a GPU win, and did it
survive into the frame? A static win with no frame win is still a finding — it
says the metric you optimised was not the bottleneck.

M1 and M2 work. M3 is designed, not built (`docs/SHADERBENCH_PLAN.md`).

## What a `.foz` is

A Fossilize database: tagged, content-addressed records of Vulkan object
creation. Steam's own Fossilize layer writes one for every Proton game, with no
instrumentation from us — **playing the game is the capture step**.

| tag | object | remnant2 | metro-ee |
|---:|---|---:|---:|
| 2 | descriptor set layout | 15 | 19 |
| 3 | pipeline layout | 165 | 102 |
| 4 | shader module (SPIR-V) | 12,307 | 44,647 |
| 5 | render pass | 0 (dynamic rendering) | 6 |
| 6 | graphics pipeline | 5,035 | 102,393 |
| 7 | compute pipeline | 8,088 | 213 |

**It contains** the SPIR-V, the full create-infos, descriptor set layouts,
pipeline layouts and render passes — everything needed to *create* a pipeline.

**It does not contain** draws, dispatches, resource contents, descriptor
bindings, push-constant values, or any scene/frame structure. It records
pipeline **creation**, never use.

Two consequences that constrain every claim:

1. A pipeline in the database was compiled at some point. It was **not**
   necessarily drawn. RenderDoc frames are the only ground truth for that.
2. Pipeline creation collapses after first encounter. Three sequential runs of
   the same Metro EE benchmark created **63,699 → 2,526 → 1,178** graphics
   pipelines. By the time FPS is steady the hot shaders are already compiled and
   cached, so a "constant-FPS window" captures the leftovers, not the hot set.
   Scene hotness needs RenderDoc or SQTT; the `.foz` cannot answer it.

## The chain

```
play the game            Steam's Fossilize layer records into the shadercache
  ↓ tcc collect          copy out + sha256 verify, before Steam wipes it
  ↓ tcc collect --check  what would I lose by uninstalling? (exits 1 if at risk)
  ↓ tcc corpus build     merge every .foz for the game, keep provenance
  ↓ tcc stats run        replay under a driver → per-stage compiler stats
  ↓ tcc mine             rank offenders worth disassembling
  ↓ tcc compare          diff two compilers over identical input
```

### Replay recompiles; it does not execute

`fossilize-replay` hands the recorded SPIR-V and state back to RADV, which
**compiles it again** — SPIR-V → NIR → ACO → gfx1101 machine code. Nothing is
drawn, nothing is dispatched, no shader runs on the GPU.

That is why M1 is perfectly deterministic and needs no game, and equally why M1
alone cannot tell you a frame got faster. Cost: ~350 pipelines/s; remnant2's
13,180 replay in ~70 s.

`--enable-pipeline-stats` makes the driver report on itself via
`VK_KHR_pipeline_executable_properties`: one CSV row per pipeline **stage**.

### Merging is a union, not a concatenation

Content addressing means merging N databases deduplicates by construction.
Analysing one arbitrarily-chosen file discarded up to 52% of a game's data;
`tcc corpus build` merges all of them. Measured: cyberpunk2077 19,316 → 23,365
graphics pipelines (+21.0%), kh3 83,283 → 99,493 (+19.5%).

Merging erases the file boundary between `run_recorded` and `steam_precache`, so
the hash→provenance index is built **before** the merge and rejoined as a
`provenance` column.

### Three file classes, not interchangeable as evidence

- **`run_recorded`** (`steamapprun_*`) — compiled by *this* machine. The only
  class that proves the local GPU and driver did the work.
- **`steam_precache`** — may be Steam's downloaded community cache. Shader
  material, never evidence of what ran here.
- **`whitelist`** — Valve's curated set.

Steam can download its pre-cache *mid-session* (observed: 142 MB landing during
a Metro EE run), which is why `delta()` reports `new` and `run_created`
separately and analysis uses `run_created`.

## Metrics vocabulary

From `fossilize-replay --enable-pipeline-stats`, all first-class columns:

- `vgprs`, `sgprs` — allocated registers; high VGPR count limits occupancy.
- `max_waves` (raw: "Subgroups per SIMD") — occupancy ceiling per SIMD.
- `spilled_vgprs/sgprs` — the compiler ran out of registers and went to memory.
- `code_size`, `lds`, `scratch` — footprint.
- `subgroup_size` — **wave32 or wave64**. Load-bearing: VOPD is only emitted for
  wave32.
- ACO counters: `instructions`, `copies`, `branches`, `latency`,
  `inverse_throughput`, `vmem_clause`, `smem_clause`, `valu`, `salu`, `vmem`,
  `smem`, `vopd`.
- `vopd_ratio` = `vopd / valu`, derived in `compare.py`. **Never compare raw
  `vopd`** — it rises when a shader merely gets bigger.
- `provenance` — `run_recorded` / `steam_precache`, joined from the corpus index.

From `fossilize-disasm --target isa` (top-N offenders only; `isa.py` not written):

- Three sections per file: NIR, ACO IR, and **Final Assembly** — the real RDNA3
  ISA with `s_`/`v_` mnemonics.
- `stall_ratio` = (`s_delay_alu` + `s_waitcnt`/`s_wait_*` + `s_nop`) / total.
  RDNA3 removed hardware interlocks for VALU hazards; the compiler must insert
  `s_delay_alu`, so this measures hazard-handling overhead.

Runtime: MangoHud frametime CSVs (avg fps, 1%/0.1% lows). Frames slower than
200 ms are dropped as pauses — `autostart_log` records menus and load screens as
single multi-minute "frames", and one 57-minute frame poisons every mean.

## The hypotheses, and where they stand

- **`s_delay_alu` cost** — needs `isa.py`. Not measured yet.
- **VOPD underuse** — reframed by measurement. VOPD requires wave32; ACO picks
  wave64 for 98.6% of remnant2's shaders and emits VOPD in 244 of the 248 wave32
  ones. So it is a **wave-size selection** outcome, not a failure to find
  dual-issue pairs. ⚠️ **n = 1 game.** Needs the corpus replay grouped by
  `cohort` and `api` before it generalises. `RADV_PERFTEST=cswave32,pswave32,gewave32`
  is the real independent variable.
- **VGPR pressure / occupancy** — `max_waves` is collected; no calibration
  against measured FPS yet.

## The modification

`custom_mesa_layer/` is an 82-file overlay of ACO. `scripts/build_custom_aco.sh`
rsyncs it into `lib/mesa/` and builds into `build/install_custom/`.

**Currently zero files differ from stock** — verified by
`diff -rq custom_mesa_layer/src/amd/compiler lib/mesa/src/amd/compiler`. The two
`.so` files have different sha256 only because RADV bakes its install path in;
a hash difference does **not** prove a functional difference. The null A/B is
what proves they are functionally identical, and it passes: 17,725 joined rows,
19 metrics, zero deltas.

Driver selection is by ICD manifest: `system` (distro Mesa 25.2.8), `stock`
(`build/install`, reports Mesa 26.1.0-devel), `custom` (`build/install_custom`).
`config.profile_env()` is the single place `VK_ICD_FILENAMES`, `RADV_DEBUG` and
`MESA_SHADER_CACHE_DIR` are computed.

## Getting a modified compiler into a real game

Steam launches the game inside Proton inside pressure-vessel; you cannot pass it
environment variables from outside. So:

Launch options are set **once** per game to `bin/tcc-launch.sh %command%`.
Per-experiment state goes to `~/.tcc/armed.{json,env}` — under `$HOME` because
pressure-vessel mounts `$HOME` but not `/tmp`. The wrapper exports the variables,
logs the launch, and consumes the profile. One-shot by default plus a TTL: two
independent guards, because a contaminated A/B looks exactly like a real result.

Its contract: **never break a launch.** Every failure path ends in `exec "$@"`.

## The session model

Everything is session-scoped:
`data/sessions/<game>/<YYYYMMDD-HHMMSS>_<game>_<scene>/` with `session.json`
(schema-validated manifest, step log, **tool resolution**, **per-step
environment snapshot naming the ICD**) and `artifacts.json` (sha256 + a
`confidence` label of `exact`/`strong`/`weak`/`unresolved`).

## Honesty rules

- Exact pipeline hashes are the join key end to end. Heuristic linkage is
  labelled, never implied as exact.
- A/B runs are cache-clean: `RADV_DEBUG=nocache` + isolated
  `MESA_SHADER_CACHE_DIR`, enforced in `config.profile_env()`.
- `scene.foz` from `fossilize-prune --filter` is a **superset** — it retains
  ~77–87 unrelated pipelines regardless of what was requested. Never call it
  "the scene's pipelines"; filter the stats table by the hash list instead.
- Confirm which driver actually loaded before trusting a comparison. The
  recorded `env_snapshot` names the ICD; the version strings differ (26.1.0-devel
  local vs 25.2.8 system).
- Report failures with counts — replay timeouts, skipped RT pipelines, collapsed
  duplicate rows — never silently drop.

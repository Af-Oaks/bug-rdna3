# Domain Summary

Fast context for working in this repo: what is being measured, with which tools, and what the
words mean. The live status tracker is [`TODO.md`](TODO.md); the approved rework plan is
[`docs/PLAN.md`](docs/PLAN.md); agent rules are in [`AGENTS.md`](AGENTS.md).

## Core Framing

- Investigate and measure which workload, pipeline, shader, compiler, and runtime
  characteristics correlate with **high vs low gains on RDNA3** relative to RDNA2-era
  expectations. Never frame as "proving a flaw".
- Comparison axes: high-gain vs low-gain titles; baseline ACO vs custom-modified ACO;
  synthetic microbenchmarks vs real scenes.
- Hardware: RX 7800 XT = Navi 32 = **gfx1101** (gfx1100 is Navi 31 — wrong chip).
- Stack: Linux + Steam/Proton + Vulkan + Mesa RADV + ACO. Games running through
  VKD3D-Proton (DX12 titles) still produce Vulkan pipelines that Fossilize records.

## Metrics Vocabulary (what the thesis measures)

Per-stage compiler stats (from `fossilize-replay --enable-pipeline-stats`, i.e.
`VK_KHR_pipeline_executable_properties` — RADV/ACO reports these directly):

- `vgprs`, `sgprs` — allocated registers; high VGPR count limits occupancy.
- `max_waves` (raw name "Subgroups per SIMD") — occupancy ceiling per SIMD.
- `spilled_vgprs/sgprs` — register spills (very bad; weighted 3x in offender score).
- `code_size`, `lds`, `scratch` — footprint metrics.
- ACO extras (in the `extra` column): `Instructions, Copies, Branches, Latency,
  Inverse Throughput, VMEM/SMEM Clause, Pre-Sched SGPRs/VGPRs, VALU, SALU, VMEM, SMEM,
  VOPD` — note **VOPD (dual-issue) counts come straight from the driver**.

ISA-text metrics (from `fossilize-disasm --target isa`, only for top-N offenders;
formulas ported from the legacy `triage.py`, names appear in the thesis):

- `stall_ratio` = (s_delay_alu + s_waitcnt/s_wait_* + s_nop) / total_instructions —
  software-stall density. RDNA3 has no hardware interlocks for VALU hazards; the compiler
  must insert `s_delay_alu`, so this measures hazard-handling overhead.
- `vopd_ratio` = v_dual_* / total_instructions — how often dual-issue is actually used.
- Hazard DAG (`tcc/hazards.py`): RAW-dependency graph over the ISA; theoretical stall cycles
  where scheduled distance < instruction latency.

Runtime metrics:

- Frametime CSVs via mangohud (avg fps, 1%/0.1% lows, percentiles) for real games.
- `median_ns` per dispatch from the shaderlab C++ harness (GPU timestamp queries) for
  authored microbenchmarks.
- Optional: SQTT/RGP thread traces (`RADV_THREAD_TRACE_TRIGGER`) for wave-level timelines.

## The Session Model

Everything is scoped to a session: one game + one scene/benchmark + one timestamp.
`data/sessions/<game>/<YYYYMMDD-HHMMSS>_<game>_<scene>/` holds manifests (`session.json`,
`artifacts.json` — schema-validated, sha256 provenance, step records) and artifact dirs
(`foz/`, `stats/`, `isa/<driver>/`, `captures/`, `bench/`, `reports/`, `logs/`).
Driver variants within a session: `system` (distro Mesa), `stock` (local build),
`custom` (local build with `custom_mesa_layer/` ACO changes), `llvm` (stock + RADV_DEBUG=llvm).

## Canonical Workflow (stats-first)

1. `tcc session new --game X --scene Y`
2. `tcc foz snapshot --label before` → `tcc arm --profile <p>` → launch → play/bench →
   `tcc foz snapshot --label after`
3. `tcc foz delta` → `tcc foz extract` (scene-scoped `scene.foz` via fossilize-prune)
4. `tcc stats run --driver stock` and `--driver custom` (exact-hash per-stage stats)
5. `tcc mine --top 25` (offender score: z(vgprs) + z(-max_waves) + z(code_size) + 3·z(spills))
6. `tcc isa extract --top 25` + `tcc isa metrics [--deep]` (stall_ratio, vopd_ratio, DAG)
7. `tcc compare --a stock --b custom` (+ `tcc isa diff --hash H` for thesis money-shots)
8. `tcc rga run --top 10` (independent static occupancy cross-check, gfx1101)
9. `tcc report session` → markdown evidence.

Key caveat: Fossilize records pipelines at **creation** time (UE5 precreates PSOs at load),
so a foz delta means "created during the window", not "drawn in the scene". RenderDoc
captures (`tcc capture rdc`, via Steam's own `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` layer)
are the on-screen ground truth when scene-exactness matters.

## Game Matrix (three automation tiers)

- **Tier 0 — synthetics, fully scriptable, no gameplay**: vkmark, vkpeak, GravityMark,
  vkcube (wrapper test target). Primary vehicle for stock-vs-custom ACO A/B loops.
- **Tier 1 — built-in benchmarks (launch + one menu click)**: Cyberpunk 2077 (1091500,
  VKD3D, high-gain), Shadow of the Tomb Raider (750920, native Vulkan, reference),
  Black Myth: Wukong Benchmark Tool (**3132990**, UE5), FFXV Windows Benchmark
  (non-Steam, Proton).
- **Tier 2 — manual scene protocols**: Remnant II (1282100, UE5, installed),
  Control (870780). Scene protocols documented in `docs/scenes/`.

## Tool Policy

Resolution order (implemented in `tcc.toolchain`): repo-local builds (`build/install/bin`)
→ vendored prebuilts (`tools/`) → system PATH. Every resolved path is recorded in the
session manifest. Missing tools are reported honestly (`tcc doctor` gives remedies).
Nothing is installed silently; sudo installs are human tasks listed in TODO.md.

## Honesty Rules

- Exact pipeline hashes are the join key end-to-end; when only heuristic linkage exists
  (e.g. foz window ↔ RenderDoc frame), label it explicitly — never imply exactness.
- A/B runs must be cache-clean: `RADV_DEBUG=nocache` + isolated `MESA_SHADER_CACHE_DIR`
  (enforced centrally in `tcc.config.profile_env`).
- The shaderlab harness records the device/driverInfo string in its output JSON — always
  check it to confirm which driver actually loaded before trusting a comparison.
- Report failures (replay timeouts, skipped RT pipelines) with counts, never silently drop.

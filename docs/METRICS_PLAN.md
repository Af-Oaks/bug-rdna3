# Two-Metric Loop — Compiler Efficiency (static) + Runtime Impact (dynamic)

Plan for the measurement core of the TCC: a **self-feeding loop** where a cheap,
game-free *static* metric predicts the direction/magnitude of an FPS change, and an
expensive *runtime* metric calibrates and audits that prediction. Target: RX 7800 XT
(RADV NAVI32 / **gfx1101**), Linux + Steam/Proton + Mesa RADV/ACO, stock
(`build/install`) vs custom (`build/install_custom`) compiler.

Read alongside `docs/PLAN.md` (master repo plan; this doc expands its Phase 4 `compare.py`
and Phase 6 `bench.py`) and `docs/THESIS_NOTES.md`.

---

## 0. TL;DR

- **Metric 1 — Compiler Efficiency (static, game-free, per build):** replay a captured
  `.foz` pipeline database through stock and custom RADV with
  `fossilize-replay --enable-pipeline-stats`, then diff the two stat tables. Answers
  *"did the compiler get better/worse, and where?"* Deterministic, minutes, 100%
  attributable to the compiler. **Built:** `stats.py`, `mine.py`. **Missing:** `compare.py`.
- **Metric 2 — Runtime Impact (dynamic, real scene, oracle):** run the game's built-in
  benchmark under MangoHud, get FPS/frametime. Answers *"what actually happened to the
  frame."* **Built and validated on Metro EE** (`bench.py`).
- **The bridge (new work):** static deltas alone cannot yield FPS (proven below). We
  connect the two by (a) *weighting* Metric 1 by which pipelines are actually hot in the
  scene and (b) recording a *calibration* of "static delta → measured FPS delta" across a
  best-case…worst-case game cohort (Cyberpunk 2077 → Shadow of the Tomb Raider). Once the
  calibration holds, Metric 1 predicts and you re-run Metric 2 only to validate.
- **The honest claim for the defense:** you never derive FPS from the foz; you stop
  needing the game *on every iteration*. The game remains ground truth for calibration and
  audit.

---

## 1. Why two metrics — the epistemics

### 1.1 What the static metric is

`--enable-pipeline-stats` re-issues every `vkCreate*Pipelines` call recorded in the foz and
reports, **per shader stage**, the compiler's output: VGPRs/SGPRs, spilled VGPRs/SGPRs,
code size, LDS, scratch, max waves/SIMD (occupancy), instruction/VALU/SALU/VMEM/SMEM/VOPD
counts, plus ACO's own `Latency` and `Inverse Throughput` estimates. This is the
**compiler's product, measured** — deterministic and fully attributable, because both
drivers consume byte-identical inputs.

### 1.2 Why it is NOT the runtime of the scene

Confirmed correct: static stats are a *proxy*, not runtime. Four reasons, each a design
constraint on the loop:

1. **No execution weighting.** Frame cost ≈ `Σ over draws (per-invocation cost × invocation
   count × draw count)`. Fossilize treats all pipelines as equals; at runtime a handful
   dominate. A regression on a **cold** pipeline (compiled, rarely/never drawn) → ~0 FPS
   impact; the same regression on the **hot** full-screen fragment shader → large impact.
   Static stats cannot tell these apart. → *drives the weighting bridge, §4.*
2. **`Latency` / `Inverse Throughput` are ACO model estimates, not measured cycles.** They
   come from ACO's internal instruction cost model and assume no memory stalls, no cache
   misses, no wave contention, ideal issue. Real frames are dominated by exactly those.
3. **No memory-system behavior.** Two ISAs with identical VGPR/instruction counts can differ
   sharply at runtime if one's access pattern thrashes L2/VRAM. The foz has no draw/resource
   data, so replay can never see this.
4. **VGPR→occupancy is the strongest predictor, still only a predictor.** Fewer VGPRs → more
   resident waves → better latency hiding — *usually*. A shader bottlenecked elsewhere gains
   nothing.

**Conclusion:** static stats are a leading indicator — cheap, directional, reproducible —
but the runtime truth requires execution. Hence Metric 2 is mandatory, not optional.

### 1.3 Three axes actually available (two primary + one free)

| Axis | Tool | What it measures | Cost | Role |
|---|---|---|---|---|
| **Static quality** (Metric 1) | `fossilize-replay --enable-pipeline-stats` | compiler output per shader | minutes, game-free | inner loop / predictor |
| **Runtime** (Metric 2) | `bench run` + MangoHud | real FPS/frametime of the scene | ~5 min, needs game | oracle / calibrator |
| **Compile throughput** (bonus) | `fossilize-replay` wall time, `fossilize-bench` | how fast the compiler emits pipelines | free (same replay) | shader-comp **stutter**, not steady FPS |

The bonus axis is free from the same replay and is genuinely thesis-relevant: compile time
drives traversal-stutter/hitching (a real RDNA3 pain), which steady-state FPS hides.

---

## 2. Metric 1 — Compiler Efficiency (static)

### 2.1 Data flow (mostly built)

```
captured .foz (session/foz/scene.foz)
   │  tcc stats run --driver stock     → stats/stats.stock.csv   (VK_ICD → build/install)
   │  tcc stats run --driver custom    → stats/stats.custom.csv  (VK_ICD → build/install_custom)
   │      each: fossilize-replay --enable-pipeline-stats, RADV_DEBUG=nocache forced
   ▼
tcc compare --a stock --b custom       → stats/compare.stock_vs_custom.{json,md}   ← MISSING
   │  join on (pipeline_hash, stage); per-metric deltas; aggregate verdict
   ▼
tcc mine --driver custom --top N        → worst-offender ranking (built)
```

`stats.py` already: resolves `driver → profile → VK_ICD_FILENAMES` (`config.resolve_icd`),
runs `foz.replay_stats` (`--num-threads`, `--timeout-seconds`; defaults 4 / 30s in
`config.defaults`), parses the CSV into the tidy schema, writes `stats.<driver>.csv`, logs
stdout/stderr and a `record_step` with `num_rows`/`failure_count`.

`mine.py` already: per-stage z-score offender score
`z(vgprs) + z(-max_waves) + z(code_size) + 3·z(spilled_vgprs)`.

### 2.2 Columns

Currently promoted by `stats._classify_column`: `driver, pipeline_hash,
driver_pipeline_hash, pipeline_type, stage, vgprs, sgprs, spilled_vgprs, spilled_sgprs,
code_size, lds, scratch, max_waves` (from "Subgroups per SIMD"); everything else lands in
the `extra` JSON column.

**Task M1-A — promote thesis-relevant columns out of `extra`.** Extend `_classify_column`
(substring-tolerant, keep the existing "driver pipeline hash" and "pre-sched" guards) to
also classify: `instructions`, `latency` (ACO "Latency"), `inverse_throughput` ("Inverse
Throughput"), `valu`, `salu`, `vmem`, `smem`, `vopd`, `branches`, `copies`. These are the
per-shader signals the compare/weighting steps need as first-class numeric columns. Bump
`schemas/stats_table.schema.json` accordingly. Unmatched columns still fall through to
`extra` (forward-compatible with Fossilize header drift).

### 2.3 `compare.py` — the missing piece (Phase 4)

CLI (stub already wired in `cli.py`: `--session --a --b --llvm --out`):

```
tcc compare --session <id> --a stock --b custom [--weight-by none|run_created|sqtt|shaderlab]
            [--out <path>] [--llvm]
```

**Algorithm**

1. Load `stats/stats.<a>.csv` and `stats/stats.<b>.csv`.
2. **Join** on `key = (pipeline_hash, stage)`. Both sides replay the *same* foz, so the key
   sets should match. Rows present in one side only = **compile-divergence** (a pipeline one
   driver compiled and the other rejected/failed) — surface these explicitly; they are a
   finding, not noise.
3. **Per-row deltas** (`b − a`) for every numeric column: `d_vgprs, d_sgprs,
   d_spilled_vgprs, d_code_size, d_max_waves, d_instructions, d_latency,
   d_inverse_throughput, d_valu, d_salu, d_vmem, d_vopd, …`.
4. **Per-metric aggregate:** `n_improved`, `n_regressed`, `n_unchanged`, `sum`, `mean`,
   `p50`, `p95`, `max|Δ|`, and the top-N pipelines by `|Δ|`. Direction convention: *lower is
   better* for vgprs/sgprs/spills/code_size/scratch/lds/instructions/latency/
   inverse_throughput; *higher is better* for `max_waves` (occupancy). Normalize so
   "improved/regressed" is unambiguous per column.
5. **Occupancy call-out:** `max_waves` is the single most runtime-predictive column — report
   `n(Δmax_waves<0)` (occupancy regressions) and `n(Δmax_waves>0)` prominently.
6. **Weighting (`--weight-by`, see §4):**
   - `none` — unweighted (default; correct for the null sanity check).
   - `run_created` — keep only pipelines in this session's `foz/delta.json → run_created`
     (the pipelines the scene actually compiled), excluding the community pre-cache. Coarse
     relevance filter, zero extra capture cost.
   - `sqtt` — weight each pipeline's delta by its real frame-time share from an RGP trace
     (§4.2). Gold standard.
   - `shaderlab` — weight by standardized per-shader GPU ns from the shaderlab harness (§4.3).
7. **Headline verdict:** `identical` (all Δ = 0 — the null A/B) / `net-improvement` /
   `net-regression` / `mixed`, plus a single **weighted static score** =
   `Σ pipelines w_p · (α·Δvgpr_norm + β·(−Δmax_waves) + γ·Δspill + δ·Δinstr + …)` with weights
   `w_p` from step 6 and per-metric coefficients documented in the config (start:
   spill≫vgpr≈occupancy>instr>latency-model). This scalar is what the calibration in §5
   regresses against measured FPS.

**Outputs**
- `stats/compare.<a>_vs_<b>.json` — machine record: per-metric aggregates, divergence lists,
  top movers, weighted score, provenance (foz hash, driver build strings, weighting source).
- `stats/compare.<a>_vs_<b>.md` — human table (verdict banner, per-metric summary, top-20
  regressions/improvements, occupancy call-out, compile-divergence list).
- Registered as artifacts (`session.record_artifact`, `confidence="exact"`).

`--llvm`: `a`/`b` may name an LLVM-backend RADV variant instead of ACO, to compare
**ACO vs LLVM** on the same foz (ties into shaderlab Phase 5). Semantics: `--llvm` selects
the `*.llvm` stats table produced by a `RADV_DEBUG=llvm`-style profile run.

### 2.4 First result must be the null A/B

Custom is currently the same source revision as stock (both report `Mesa 26.1.0-devel
git-6e3d805735`; the `.so` sha differs only because RADV bakes in the install path and is
not reproducible). Therefore **`tcc compare --a stock --b custom` must report ~zero deltas
everywhere.** That zero is the proof the entire Metric-1 chain (capture → replay → parse →
join → aggregate) is sound *before* the custom compiler ever diverges. Any non-zero here is
either a real divergence or a harness bug — both must be explained.

---

## 3. Metric 2 — Runtime Impact (dynamic)

### 3.1 Data flow (built, validated on Metro EE)

```
tcc bench run --game <slug> --profile bench-mangohud [--exe-override ...]
   session → foz snapshot(before) → arm(mangohud autostart) → launch via Steam wrapper
   → [human triggers the built-in benchmark] → wait for exit
   → foz snapshot(after) + delta → parse MangoHud CSV → bench/bench_summary.json
```

Validated result (Metro EE, session `20260724-101611`): 52.8 fps avg, p50 18.8 ms,
1%/0.1% low 37.4/34.3 fps, 5810 frames / 110 s; foz run-created delta 1178 gfx.

### 3.2 Pause-frame filtering (fixed)

`autostart_log=1` logs the whole process lifetime, so menu-in / between-run / results
screens appear as multi-minute "frames". `bench.parse_mangohud_csv` now drops frametimes
> `PAUSE_FRAMETIME_MS` (200 ms = 5 fps floor), aggregates only rendered frames, and reports
`pause_frames_dropped` / `raw_frames`. Applies to every menu-triggered benchmark.

### 3.3 What Metric 2 owns

- **The FPS/frametime the thesis reports** (avg, 1% low, 0.1% low, p50/p95/p99/p999 frametime).
- **The cohort spread.** A single game cannot calibrate a proxy; the range from best case
  (Cyberpunk 2077, near-zero gen-over-gen regression) to worst case (Shadow of the Tomb
  Raider) is the signal the static metric must reproduce. The game TOMLs already carry a
  `cohort` field (`high-gain`/`low-gain`) — that IS the calibration axis. Run Metric 2 across
  the cohort, not one title.
- **Multi-run stability.** Support `--runs N` (repeat the built-in benchmark, keep each
  CSV), report median + run-to-run variance so a static prediction is compared against a
  stable oracle, not a single noisy sample.

### 3.4 Task list

- **M2-A — `--runs N`** in `bench run`: loop the benchmark trigger, one CSV per run,
  `bench_summary.json` reports per-run + aggregate (median FPS, CV%).
- **M2-B — cohort execution:** set Steam launch options + capture a baseline Metric-2 run
  for each cohort game (Metro EE ✓; then Control, CS2, RE Requiem; later Cyberpunk, SOTTR).
- **M2-C — driver A/B at runtime (optional, expensive):** the same game benchmark under
  stock vs custom RADV (via `arm --profile` ICD swap) to get a *measured* FPS delta for the
  calibration rows. Only meaningful once custom actually diverges.

---

## 4. The bridge — weighting Metric 1 by what's hot

The core weakness of Metric 1 (§1.2 reason 1) is equal treatment of all pipelines. The
bridge supplies per-pipeline **weight** = share of real frame time. Three sources, MVP→gold:

### 4.1 `run_created` relevance filter (MVP, zero extra cost)

Keep only pipelines in `foz/delta.json → run_created` — the ones this scene actually
compiled — dropping the community pre-cache the scene never used. Not true weighting, but a
strong, free relevance filter that already stops "improved a shader the scene never runs"
from polluting the verdict. Ship this first (`--weight-by run_created`).

### 4.2 SQTT / RGP thread trace (gold, real weights)

The `capture-sqtt` profile exists (`sqtt=true`; `config.profile_env` sets
`RADV_THREAD_TRACE_TRIGGER = <session>/sqtt.trigger`). Run one bench pass with it → RADV
emits an `.rgp` thread trace with **real per-shader wavefront occupancy and GPU time**. That
gives the true weight and the hot-pipeline set.

- **Caveat (be honest):** programmatic RGP parsing is a sub-project — the format is
  AMD-tool-oriented (Radeon GPU Profiler GUI). Task **M-SQTT** is scoped as: (1) confirm
  RADV emits the trace on trigger during a Proton bench; (2) evaluate extraction paths
  (`rgp`/Radeon Developer tooling CLI export → CSV, or SQTT→CSV if available) — do **not**
  hand-roll a full RGP binary parser; (3) if no clean CLI export exists, fall back to §4.1 +
  §4.3 and record SQTT as "visual audit only".
- Join RGP shader hashes ↔ Fossilize `driver_pipeline_hash` to attach weights to compare rows.

### 4.3 Shaderlab standardized re-execution (controlled runtime, game-free)

Phase 5's Vulkan dispatch harness (`shaderlab/`) can take a hot pipeline and *actually run
it on the GPU* under a fixed, standardized invocation (e.g. fullscreen quad for fragment,
declared workgroup × N for compute) and time it (`median_ns`). This is **runtime-real
per-shader timing without the game**, at the cost of synthetic (chosen, not scene-true)
invocation counts. Use it to (a) sanity-check that a static delta actually moves GPU time,
and (b) weight compare when no RGP trace exists. `--weight-by shaderlab`.

---

## 5. Calibration & the self-feeding loop

### 5.1 The calibration record

A persistent table tying the two metrics together, one row per (game, scene, driver-pair)
where **both** metrics were run:

`data/calibration/metric_correlation.csv`
```
game, scene, cohort, driver_a, driver_b, date,
static_score_unweighted, static_score_weighted, weight_source,
fps_delta_pct, frametime_p99_delta_pct, fps_avg_a, fps_avg_b,
compile_divergence_count, notes, session_a, session_b
```

- `static_score_*` from `compare.py` (§2.3 step 7).
- `fps_delta_pct`, `frametime_p99_delta_pct` from the two Metric-2 runs (§3).
- Appended by a new `tcc calibrate add --session-a … --session-b …` (or emitted directly by
  `compare` when both runtime summaries are present).

### 5.2 Fitting

`tcc calibrate fit` regresses measured `fps_delta_pct` on `static_score_weighted` (and
optionally raw aggregate deltas) across all rows, reports:
- coefficient(s) + **R²** and residuals per game,
- the best-case…worst-case span (Cyberpunk vs SOTTR) the model must bracket,
- a **prediction interval** — so a future Metric-1-only run yields "FPS likely `X% ± CI`",
  not a false point estimate.

The thesis claim becomes defensible: *"static compiler metrics predict measured FPS delta
with R²=…, calibrated over an N-game cohort spanning +…% to −…% gen-over-gen; residuals
bounded by …%."* That is the honest form of "we don't need to run the game every time."

### 5.3 Operating protocol (the loop)

```
1. Build custom compiler.
2. METRIC 1 (inner, every build): stats run stock+custom on the scene.foz cohort
   → compare --weight-by run_created (or sqtt) → weighted static score + top movers.
3. Predict: feed the score through the calibration → "FPS likely ±X% (CI)".
4. Gate:
     • |predicted| small AND within model's validated range → trust it, iterate (no game).
     • |predicted| large, OR out-of-range, OR occupancy/spill regressions on hot shaders,
       OR periodic audit due → run METRIC 2 (bench+MangoHud) on the anchor games.
5. METRIC 2 result → append a calibration row → refit. Loop.
```

Recalibrate whenever prediction residuals grow or the compiler change touches a class of
shaders not represented in the calibration set.

---

## 6. Implementation plan (ordered, with acceptance criteria)

Style mirrors `docs/PLAN.md` §7. `[GPU]` needs the card; `[HUMAN]` needs a person at Steam.

- **M1-A — stats parser: promote columns.** Extend `stats._classify_column` + schema for
  `instructions, latency, inverse_throughput, valu, salu, vmem, smem, vopd, branches,
  copies`. ✓ re-parsing an existing `_raw.*.csv` yields these as numeric columns, `extra`
  shrinks, old columns unchanged.
- **M1-B — run the staged replays `[GPU]`.** `tcc stats run --driver stock` and
  `--driver custom` on `data/sessions/metro-ee/20260724-101611…/foz/scene.foz` (102,393 gfx
  + 213 compute; ~8–10 min each). ✓ two `stats.<driver>.csv`, >100k rows each, non-null
  vgprs/max_waves, `failure_count` logged.
- **M1-C — `compare.py` (Phase 4).** Implement §2.3 (join, per-metric aggregates,
  divergence, verdict, weighted score, `--weight-by none|run_created`, json+md out). Wire
  into `cli.py` (replace the stub). ✓ **`tcc compare --a stock --b custom` on M1-B prints
  the null verdict `identical` (all Δ≈0)** — the harness sanity check; md/json artifacts
  registered.
- **M2-A — `bench run --runs N`.** Loop trigger, per-run CSV, median + CV% in summary.
  ✓ a 3-run vkmark/Metro summary shows 3 runs + aggregate with variance.
- **M-WEIGHT-1 — `--weight-by run_created`.** Filter compare to the session's run_created
  set. ✓ compare row count drops to the run_created pipeline count; verdict recomputed.
- **M-SQTT — RGP capture + extraction spike `[GPU][HUMAN]`.** §4.2: confirm trace emission
  under Proton, evaluate a CLI export to per-shader time; deliver either a parser adapter or
  a documented "visual-only" fallback. ✓ either a `sqtt/*.csv` with per-shader ns joined to
  pipeline hashes, or a written decision to rely on §4.1/§4.3.
- **M-WEIGHT-2 — `--weight-by sqtt|shaderlab`.** Attach weights from M-SQTT or shaderlab
  (Phase 5) to compare. ✓ weighted vs unweighted scores differ and the hot set dominates.
- **M-CAL — calibration.** `data/calibration/metric_correlation.csv` + `tcc calibrate
  add/fit`. ✓ ≥2 rows produce a fit with R² and residuals; `fit` prints the prediction
  interval.
- **M2-B — cohort baselines `[HUMAN]`.** Metric-2 baseline per cohort game (Metro ✓ → Control,
  CS2, RE Requiem → Cyberpunk, SOTTR when bought). ✓ each has a `bench_summary.json` and a
  registered `scene.foz`.

Dependencies: M1-A → M1-C; M1-B feeds M1-C; M-WEIGHT-1 needs `foz.delta`; M-CAL needs
M1-C + M2 outputs; M-WEIGHT-2 needs M-SQTT and/or Phase 5 shaderlab.

## 7. Files touched

```
NEW  src/tcc/compare.py                 # §2.3 Metric-1 diff engine
NEW  src/tcc/calibrate.py               # §5 correlation record + fit
EDIT src/tcc/stats.py                   # M1-A: promote columns
EDIT src/tcc/schemas/stats_table.schema.json
EDIT src/tcc/bench.py                   # M2-A: --runs N
EDIT src/tcc/cli.py                     # replace compare stub; add calibrate subcommands; bench --runs
NEW  data/calibration/metric_correlation.csv   # §5.1 (created on first `calibrate add`)
DOC  docs/METRICS_PLAN.md (this file); cross-link from TODO.md / docs/PLAN.md §7
```

Config coefficients for the weighted static score live in `config/tcc.toml`
(`[metrics] weight_spill=…, weight_vgpr=…, weight_occupancy=…, …`) so the scoring is tunable
without code edits and its provenance is recorded per compare run.

## 8. Data / artifact layout

```
data/sessions/<game>/<id>/
  foz/scene.foz                       # staged replay input (symlink to after/*.foz)
  foz/delta.json                      # new / run_created hash sets (weighting source)
  stats/_raw.<driver>.csv             # fossilize-replay raw output
  stats/stats.<driver>.csv            # tidy table
  stats/compare.<a>_vs_<b>.json/.md   # Metric-1 verdict  ← NEW
  sqtt/*.rgp, sqtt/*.csv              # RGP trace + extracted per-shader weights  ← NEW (M-SQTT)
  bench/<run>.csv, bench/bench_summary.json   # Metric-2 runtime
  logs/, session.json, artifacts.json
data/calibration/metric_correlation.csv       # cross-session bridge  ← NEW
```

## 9. Risks & honesty caveats (for the defense)

1. **"Static predicts FPS" is a calibrated empirical claim, not a derivation.** Always report
   R²/residuals and the cohort range; never present a static delta as an FPS number without
   the calibration behind it. → §5.
2. **RGP parsing may not have a clean CLI path.** Mitigated: MVP weighting via `run_created`
   (§4.1) and controlled timing via shaderlab (§4.3); SQTT downgraded to visual audit if
   needed. The loop still functions without RGP, just with coarser weights.
3. **Null A/B must be truly null.** If `stock vs custom` shows deltas while the source is
   unchanged, stop and explain (nondeterministic build vs real bug) before trusting any later
   non-null result. → §2.4.
4. **Cohort of one is not calibration.** The Cyberpunk↔SOTTR span is the whole point; a model
   fit on one game predicts nothing. → §3.3, M2-B.
5. **Compile-time ≠ runtime.** Keep the bonus compile-throughput axis clearly separate from
   FPS; it explains stutter, not steady-state, and must not leak into the FPS calibration.
6. **Constraints unchanged (AGENTS.md):** no GFXReconstruct / hand-injected Vulkan layers in
   Proton; no multi-GB RADV_DEBUG dumps; no `*.foz` globbing (resolve via
   `steam.library_folders`); automation state under `$HOME`, never `/tmp`, for Proton games.

## 10. Definition of done

- `tcc compare --a stock --b custom` yields the null verdict on the Metro foz (harness proven).
- `bench run --runs 3` yields a stable multi-run runtime summary.
- ≥2 cohort games have both a Metric-1 compare and a Metric-2 runtime summary, appended to
  `metric_correlation.csv`, with a first `calibrate fit` R² reported.
- A one-paragraph, defensible statement of the calibrated static→FPS relationship exists in
  `docs/THESIS_NOTES.md`.
```

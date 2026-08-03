# Refactor Plan — 2026-08-03

Everything agreed in the nine-point review, ordered by dependency. Each item says
what it is, why, and how you will know it worked.

Defect IDs (A1, F3…) come from the 2026-08-03 code audit; that document and the
pipeline walkthrough were folded into [DOMAIN.md](../DOMAIN.md) (mechanism) and
the per-folder `src/**/CONTEXT.md` "Known problems" sections (defects) once their
findings were either fixed or relocated. Progress: [ONGOING.md](../ONGOING.md).

---

## The correction that reorders everything

"Full use of the `.foz`" means **stop analysing one arbitrarily-chosen database**.
Today `stats.py` picks a single file — `scene.foz`, or the newest `*.foz` by
mtime ([stats.py:151](../src/analysis/stats.py#L151)). Every other file collected
for that game is ignored.

Measured cost, 2026-08-03:

| game | files | total | best single file | ignored |
|---|---:|---:|---:|---:|
| re6 | 4 | 6,935 MB | 3,319 MB | **52%** |
| remnant2 | 2 | 259 MB | 129 MB | **50%** |
| helldivers2 | 11 | 4,975 MB | 2,897 MB | **42%** |
| r6siege | 9 | 502 MB | 319 MB | **37%** |
| cyberpunk2077 | 6 | 108 MB | 80 MB | **26%** |

And in pipelines, not bytes — `fossilize-merge-db` verified on real data:

```
remnant2       5,035 + 5,038 →  5,038 graphics   (union, not concatenation)
mechabellum   best 25,797    → 27,382 graphics   +6.1%
cyberpunk2077 best 19,316    → 23,365 graphics   +21.0%
```

Fossilize databases are content-addressed, so merging **deduplicates by
construction**. Merging is therefore free of double-counting risk and is the
correct default for every metric.

**The catch that shapes the design.** Merging destroys the distinction the whole
evidence chain rests on: `run_recorded` (compiled by this machine) versus
`steam_precache` (downloaded by Steam). Once merged there is no file boundary
left to tell them apart. So the hash → provenance index is built **before** the
merge and persisted beside it, and analysis joins it back on.

---

## R0 — Corpus: merge every `.foz`, keep provenance ⭐ blocking

**New:** `src/shader_extractor/corpus.py` · `tcc corpus build|show`

- Read every `.foz` in `data/foz/<slug>/`.
- **Before merging**, run `fossilize-list` per file per tag and record which
  hashes came from which file class. Persist to `data/corpus/<slug>/corpus.json`.
- Merge into `data/corpus/<slug>/corpus.foz`. Copy the **largest** file as the
  base and append the rest — `fossilize-merge-db` appends into its first
  argument, so starting from the largest minimises I/O.
- Never mutate `data/foz/` — that is the verified archive.

**Disk cost is real:** the merged corpus roughly duplicates the archive, ~20 GB
if built for all 18 games. Per-game and opt-in, never automatic.

**Provenance index shape** — only the run-recorded set is stored explicitly;
everything else is derivable, and it keeps metro-ee's 102k hashes to ~1.7 MB:

```json
{ "slug": …, "built_at": …, "sources": [{dest_name, kind, sha256, size}],
  "counts": {"graphics": {"total": N, "run_recorded": M}},
  "run_recorded": {"graphics": ["<hash>", …], "compute": […]} }
```

**Then:** `stats.py` gains a `provenance` column (`run_recorded` /
`steam_precache`) joined from the index, so every downstream table can filter to
"what this machine actually compiled" without losing the coverage that merging
bought.

**Done when:** `tcc corpus build --game cyberpunk2077` yields a corpus with
23,365 graphics pipelines against 19,316 for the best single file, and
`tcc stats run` on it produces rows labelled with provenance.

## R0b — One deterministic selection rule (audit C2)

Two functions disagree about which database is "the" database
([foz.py:219](../src/shader_extractor/foz.py#L219),
[stats.py:147](../src/analysis/stats.py#L147)), and one of them picks by
**mtime** — so re-running next month can silently select different input.

One function, one precedence, raising on genuine ambiguity:
`explicit --foz` → `data/corpus/<slug>/corpus.foz` → `<session>/foz/scene.foz` →
single file in `<session>/foz/after/` → error.

**Done when:** mtime appears nowhere in selection, and both call sites share it.

---

## R1 — Provenance and cleanup

You said: know every line, throw away dead code and compatibility.

### R1a — Reconnect the provenance backbone (A1, A2)

`provenance.run_recorded()` tees output into session logs *and records the
`VK_`/`RADV_`/`MESA_` environment*. **Nothing calls it.** No stats table on disk
records which ICD produced it; the ICD swap has only ever been proven by hand
with strace.

Route `replay_stats`, `disasm`, `extract` and `list_hashes` through it; delete
the hand-rolled logging at [stats.py:188-197](../src/analysis/stats.py#L188-L197).
Populate `session.tool_resolution` from `toolchain.resolve()` at first use.

**Done when:** a fresh `tcc stats run` writes a step record containing
`VK_ICD_FILENAMES`, and `tool_resolution` is non-empty.

### R1b — Deletions

Dead code A3 (`paths.steam_root`), A5 (`config.list_profiles`), A6 (dead `cfg`
param). Dead config B1 (`armed_profile` key), B3 (`top_n_offenders`).
Impossible compat E1 (`.get()` defaults against a schema-forbidden v1), E2
(unreachable `None` return code).

**Keep, and they are not compatibility shims:** E3 dual `.foz` layout (both live
on your drives today), E4 substring column matching (forward-compat for a tool
you rebuild). B2 `gpu_arch` and B4-B7 (`cohort`, `api`, `engine`, `runtime`) stay
— they are the schema for analysis not yet written, and `cohort`/`api` are the
grouping variables R7 needs.

### R1c — Truth in comments and schemas (D1-D4)

Rewrite `armed_profile.schema.json` against what `arm.py` actually writes and
validate it in `arm()`. Fix the `delta()` comment that misdescribes `snapshot()`'s
naming rule — `run_created` silently becomes **zero** if someone trusts it. Drop
the `stats.py:84` clause describing a guard that does not exist. Refresh
`cli.py`'s stale docstring.

### R1d — One error base class (F6) and de-duplication (C1, C2)

`CompareError` and `CollectError` escape the CLI's except tuple and print
tracebacks. The tuple has been forgotten twice; a shared `TccError` base caught
once fixes the class of bug. Consolidate the two foz-filename flatteners (C1).

---

## R2 — Analysis correctness

- **F1 · promote `Subgroup size`** — wave32/wave64 is invisible to `compare.py`
  and `mine.py` because it sits in the `extra` blob. It is the strongest
  covariate for VOPD. Two lines.
- **F3 · compare `vopd/valu`, not raw `vopd`** — a shader that merely got bigger
  currently counts as improved.
- **F4 · `mine` groups by driver** — the default pools stock and custom into one
  z-score population, duplicating every shader.
- **F5 · report the rows `groupby().first()` drops** — currently silent.
- **F7 · scope `bench summarize` to the current run** — re-running a bench in one
  session merges both into one summary.

---

## R3 — Dynamic offender chart

A self-contained HTML page over the stats table: adjust the weights, choose which
instruction counters enter the score, regroup — **all client-side, nothing
re-runs**. Z-scores recomputed in the browser.

The methodology goes **on the chart**, not in a footnote: per-stage z-scoring, the
3× spill weight, and the disclaimer that the score ranks *candidates for
inspection* and has never been calibrated against measured FPS.

⚠️ The only table on disk predates the M1-A promotion, so VOPD, VALU and
Subgroup size are still inside `extra`. The page must parse `extra` to work with
both old and new tables.

---

## R4 — `analysis/isa.py` (points 2 and 8)

Parse the `Final Assembly` section of `fossilize-disasm --target isa`; count
instruction classes per shader — `s_delay_alu` density, VOPD ratio, VALU/SALU/
VMEM/SMEM mix, clause structure — and diff A against B per shader into the
ledger. Formulas recoverable: `git show a7f0d75:_attic/prototypes/triage.py`.

**The limit, to be stated in the thesis and in the tool's own output:** static
instruction counts prove *what changed in the code*. They do not prove execution
cost. A added `s_delay_alu` costs nothing if the wave was already stalled on
memory. Connecting the two requires R5's harness or SQTT.

---

## R5 — Crash safety and the canary (point 9)

Aggressive ACO changes do not crash cleanly — they **hang the GPU**, and a lost
queue can take the desktop with it. None of this exists today.

- Run any custom-ICD workload in a **separate process** with a hard timeout;
  never in the session manager's process.
- Detect GPU reset (`dmesg` for `amdgpu` ring timeout) and record it as a
  **result**, not a hidden failure — a compiler change that hangs the GPU is a
  finding.
- Dump the compiled ISA of the shader *before* running it, so a hang leaves
  behind the code that caused it.
- `VK_EXT_device_fault` for fault addresses where available.
- Stock stays the always-available fallback ICD.

**The canary** — one small compute shader you author, known-good, runs in
seconds. Its job is "did my compiler change break correctness?" before an hour is
spent on a corpus. You do not need shader expertise for this: you are testing the
compiler, not the shader.

This is the tier below Metric 3. The **SB-0 spike** remains the gate on Metric 3
itself.

---

## R6 — Multi-phase snapshots (point 1)

`--label` is hardcoded to `before`/`after` ([cli.py:205](../src/cli.py#L205)) and
`delta()` hardcodes those two directories. Allowing arbitrary labels lets you
bracket **creation phases** — `menu`, `loaded`, `done` — and diff any pair.

**Why this replaces the idea of filtering to the constant-FPS window:** pipeline
creation collapses after first encounter. Your own three Metro EE runs:

```
run 1: 63,699 graphics created    run 2: 2,526 (4%)    run 3: 1,178 (1.8%)
```

By the time FPS is steady the shaders rendering that frame were already created
and cached, so a constant-FPS window captures the *leftovers*, not the hot set.
"Which shaders are hot in this scene" is a question the `.foz` cannot answer at
all — it needs RenderDoc (bound in frame) or SQTT (consumed GPU time), which is
the `METRICS_PLAN.md` §4 bridge.

---

## R7 — Corpus-wide VOPD correlation (point 7)

Only after R0 + R2. Replay the merged corpus per game under stock, join
`subgroup_size` against `vopd`, and group by `cohort` and `api` — the two config
fields that are currently dead and exist for exactly this.

Until then the claim stays: *"In one vkd3d-translated title, VOPD emission was
confined to wave32 shaders, which were 1.4% of the sample."*

---

## Order and rationale

| | why here |
|---|---|
| **R0, R0b** | every later measurement is wrong-scoped without it |
| **R1a** | changes what gets recorded — before the next stats run, not after |
| **R1b-d** | mechanical; makes everything after easier to reason about |
| **R2** | correctness before conclusions |
| **R3** | needs R2's columns to be worth plotting |
| **R4, R5** | R5's watchdog protects R4's disasm runs |
| **R6, R7** | R7 needs R0's coverage and R2's columns |

**Not in scope:** SB-0 / Metric 3 harness (~850 lines C++, gated on the spike);
`report.py`; RGA.

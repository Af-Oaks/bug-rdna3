# `analysis/` — turning compiler output into defensible numbers

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/analysis/` updates this file in
> the same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this package exists

This is **Metric 1: what the compiler emitted**. It is the only one of the three
measurements that is fully deterministic and needs no game running — the same
`.foz` replayed twice under the same driver produces the same numbers, every
time. That determinism is what makes it the foundation: if a compiler change
does not move anything here, there is nothing for the other two metrics to find.

The data source is `fossilize-replay --enable-pipeline-stats`, which reports the
driver's own per-stage figures — VGPRs, SGPRs, spills, code size, waves per SIMD
— plus ACO's extras: VOPD, VALU/SALU/VMEM/SMEM counts, latency, pre-scheduling
pressure. The driver already knows all of this. The earlier approach of parsing
multi-GB `RADV_DEBUG=shaders` text dumps is abandoned and must not come back.

## The files

### `stats.py` — replay, parse, save

Runs the replayer under a driver profile (`system`/`stock`/`custom` map to
`baseline`/`stock`/`custom` profiles), then parses the CSV into a tidy table at
`<session>/stats/stats.<driver>.csv`. One row per pipeline **stage**, not per
pipeline — a graphics pipeline contributes a vertex row and a fragment row.

`_classify_column()` is the interesting part and its tolerance is deliberate:
columns are matched by *substring*, so a Fossilize version that renames a header
degrades into the `extra` JSON column instead of breaking the parse. Two ordering
rules inside it are load-bearing, and one of them was a real bug caught during
verification: `Driver pipeline hash` contains the substring `pipeline hash`, so
it must be tested first, or every row's `pipeline_hash` silently becomes the
driver's internal `0x`-prefixed hash and joins against `fossilize-list` output
fail. Likewise `Pre-Sched VGPRs` contains `vgpr` and must be excluded before the
VGPR check, or scheduling-time pressure gets recorded as final register usage.

### `mine.py` — who are the worst offenders

`score = z(vgprs) + z(-max_waves) + z(code_size) + 3·z(spilled_vgprs)`

Z-scored **per stage**, because a compute shader's code-size distribution has
nothing to say about a fragment shader's. Spills carry triple weight because a
spill is a qualitatively different event from high register usage — it means the
compiler ran out and went to memory.

Its purpose is to pick the top-N shaders worth disassembling. Full ISA parsing
of every pipeline is not affordable; ranked offenders make it affordable.

### `compare.py` — the A/B, and the null verdict

Joins two stats tables on `(pipeline_hash, stage)` and diffs every shared
numeric column. Both sides replayed byte-identical input, so every difference is
attributable to the compiler.

The first result that mattered was not a finding — it was a **zero**. Stock
versus custom, with the custom ACO overlay still unmodified, must come out
`identical`. That zero is what licenses trusting any later non-zero: it proves
capture → replay → parse → join → aggregate is sound before the compiler ever
diverges. It passed on 2026-07-28: 17,719 joined rows, all 18 metrics at zero
delta, with strace confirming the two ICDs loaded genuinely different binaries
rather than silently falling back to the same one.

Direction is explicit, not assumed: `LOWER_IS_BETTER` for cost metrics,
`HIGHER_IS_BETTER` for occupancy and VOPD.

## What this package is currently missing

`isa.py` (parse Final Assembly for `s_delay_alu` density and VOPD ratio) and
`hazards.py` (the dependency DAG) are planned and not written. The formulas for
both are recoverable from git history:
`git show a7f0d75:_attic/prototypes/triage.py` and the sibling `hazards.py`.
The old `hazards.py` used `networkx`, which is no longer a declared dependency.

## Ground rules a future change must not break

- A/B replays always run with `nocache` and an isolated shader cache. That is
  enforced centrally in `config.profile_env()` — do not build environments here.
- Unrecognised CSV columns go to `extra`, never get dropped.
- A verdict is a summary, not a conclusion. `net-improvement` means the counts
  moved; it does not mean the frame got faster. Only Metric 2 can say that.

## Known problems, costs, and things I would flag

1. **The most important column is still not a column.** `Subgroup size` — wave32
   vs wave64 — sits unpromoted in the `extra` JSON blob, so `compare.py` cannot
   diff it and `mine.py` cannot rank by it. It is the single strongest covariate
   for VOPD in the data already collected: on Remnant II, 17,482 wave64 shaders
   emitted VOPD **zero** times, while 244 of 248 wave32 shaders emitted it. That
   reframes the whole VOPD hypothesis from "the compiler fails to find
   dual-issue pairs" to "the compiler almost never picks the wave size that
   allows them". Promoting it in `_classify_column()` is roughly a two-line
   change and is the highest-value edit in this package.
2. **`vopd` in `HIGHER_IS_BETTER` is a raw count, and a raw count is not a
   quality signal.** A shader with more VOPD instructions because it has more
   instructions overall is not doing better. It needs normalising — VOPD per
   VALU, or per instruction — before the "improved / regressed" columns mean
   anything. As it stands, `compare.py` will confidently report a VOPD
   improvement for a shader that simply got bigger.
3. **`tcc mine` pools drivers by default.** `--driver` defaults to `None`, which
   makes `load_session_stats()` concatenate every `stats.*.csv` in the session.
   With both stock and custom present, each shader appears twice and the
   z-scores are computed against a doubled population. Ranking is only
   meaningful within one driver; the default does the other thing.
4. **`compare_frames()` discards duplicate rows silently.** It forces a 1:1 join
   with `groupby(JOIN_KEY).first()`, which drops any second row for a
   `(hash, stage)` pair and never reports how many it dropped. The comment says
   this happens "when one pipeline reports several executables for a stage" —
   if those executables ever carry *different* stats, half the data vanishes
   without a warning. At minimum this should count and report the collapses.
5. **A comment describes a guard that does not exist.** `_classify_column()`
   says `"inverse throughput" must be tested before "throughput"`. There is no
   `throughput` branch anywhere in the function. Either the guard was removed or
   it was never needed; the comment now misleads the next reader about the
   ordering constraints, which is exactly the ordering that has already caused
   one real bug in this function.
6. **The offender-score weights are a judgement call with no calibration.** The
   `3×` on spills and the equal weighting of the other three terms are
   reasonable priors, not measured. Nothing has yet checked whether high-score
   shaders correlate with anything Metric 2 sees. Until that check exists, the
   score ranks candidates for inspection and should not be described as a
   severity measure.
7. **`CompareError` is not in `cli.main()`'s handled exception tuple**, so
   `tcc compare` with a missing stats file prints a traceback where every other
   command prints `error: ...`.

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

`subgroup_size` (wave32 vs wave64) is promoted deliberately rather than left in
`extra`: VOPD is only emitted for wave32, so it is the strongest covariate for
dual-issue and neither `compare.py` nor `mine.py` can see inside the `extra`
blob. Each row also carries `provenance` (`run_recorded` / `steam_precache`),
joined from the corpus index — merging every `.foz` for a game buys coverage but
erases the file boundary that distinguished them, so it is reattached here.

### `mine.py` — who are the worst offenders

`score = z(vgprs) + z(-max_waves) + z(code_size) + 3·z(spilled_vgprs)`

Z-scored per **(driver, stage)**. Stage because a compute shader's code-size
distribution has nothing to say about a fragment shader's; driver because the
pooled default concatenates every `stats.*.csv` in the session, and without it
each shader would be z-scored against a population containing its own duplicate.
Spills carry triple weight because a spill is qualitatively different from high
register usage — the compiler ran out and went to memory.

Its purpose is to pick the top-N shaders worth disassembling. Full ISA parsing
of every pipeline is not affordable; ranked offenders make it affordable.

### `chart.py` — re-score without re-running

The offender score is a hypothesis, not a measurement, and baking it into a
static image would freeze an uncalibrated guess into every figure. So the page
ships the raw rows and recomputes z-scores in the browser: move a weight, add
`vopd` or any other counter as a term, regroup, and the ranking updates. A
replay costs ~70 s per driver and the data does not change — only the question
does.

Everything is inlined (no CDN, no fetch), the diverging stacked bars show *why*
each shader scores where it does, and the methodology plus the "this is not a
severity measure" disclaimer are rendered on the page rather than in a footnote.
Verified against `mine.py`: identical top-3 ranking to four decimal places.

### `isa.py` — the machine code, not the driver's self-report

Everything else in this package is RADV describing its own output. `isa.py`
reads the instructions. It parses **only** the `Final Assembly` section of
`fossilize-disasm --target isa` and raises if it is absent — counting mnemonics
out of the NIR or ACO IR sections would produce plausible numbers that mean
nothing.

`stall_ratio` is the hypothesis-1 signal: RDNA3 removed the hardware interlocks
RDNA2 used for VALU hazards, so ACO must emit `s_delay_alu`, which computes
nothing. Verified on a real Remnant II compute shader — 142 `s_delay_alu`,
matching an independent grep, with the wait distances decoded — giving a
**12.85% stall ratio** for that shader.

**A count is not a cost**, and the module says so in its own output: an
`s_delay_alu` on a path already stalled on memory is free. That caveat is
written into `isa_diff.*.json` so it travels with the number.

### `chart.py` — re-score without re-running

The offender weights are an uncalibrated guess, so baking them into a static
image would freeze that guess into every figure. The generated page ships the
raw rows and recomputes z-scores in the browser: move a weight, add `vopd` or a
stall counter as a term, regroup, and the ranking updates. A replay costs ~70 s
per driver and the data does not change — only the question does. Verified: the
browser's ranking matches `mine.py` to four decimals.

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

Direction is explicit, not assumed, and has three cases rather than two:
`LOWER_IS_BETTER` for cost metrics, `HIGHER_IS_BETTER` for occupancy and
`vopd_ratio`, and `NEUTRAL` for `subgroup_size` — where a *change* is the signal
and neither direction is "better". VOPD is compared as a **ratio to VALU**, never
as a raw count, because a raw count rises when a shader merely gets bigger. When
wave size moves the report prints a dedicated warning, since VOPD only exists on
wave32 and any ratio movement must be read against that first.

Duplicate `(hash, stage)` rows are collapsed to force a 1:1 join, and the count
is **reported** — if the two sides collapse different amounts the comparison is
not like-for-like, and that has to be visible.

### `isa.py` — the machine code the compiler actually emitted

Everything above is the driver's *self-report*. This reads the instructions.
`fossilize-disasm --target isa` emits three sections per shader — NIR, ACO IR,
and Final Assembly — and only the last is real gfx1101 code; counting mnemonics
in an intermediate would measure the wrong thing, so a missing Final Assembly
section raises rather than falling back.

`stall_ratio` is the hypothesis-1 signal: RDNA3 removed the hardware interlocks
RDNA2 used for VALU hazards, so ACO must emit `s_delay_alu`, which computes
nothing. Its operands are decoded too (`VALU_DEP_1`, `SALU_CYCLE_1`, …) because
the wait *distance* distinguishes a cheap hazard from an expensive one.
Verified against an independent grep on a real Remnant II shader: 142
`s_delay_alu` in 3,314 instructions, a 12.85% stall ratio.

**The limit that travels with every number here: a count is not a cost.** An
`s_delay_alu` on a path already stalled on memory costs nothing. Static deltas
say what changed in the code; only Metric 3 or SQTT says what it cost. `diff`
writes that caveat into its own JSON output so it cannot be quoted without it.

## What this package is currently missing

`hazards.py` (the RAW-dependency DAG, for theoretical stall cycles where
scheduled distance is below instruction latency) is designed and not written.
The formula is recoverable from `git show a7f0d75:_attic/prototypes/hazards.py`;
it used `networkx`, which is no longer a declared dependency.

## Ground rules a future change must not break

- A/B replays always run with `nocache` and an isolated shader cache. That is
  enforced centrally in `config.profile_env()` — do not build environments here.
- Unrecognised CSV columns go to `extra`, never get dropped.
- A verdict is a summary, not a conclusion. `net-improvement` means the counts
  moved; it does not mean the frame got faster. Only Metric 2 can say that.

## Known problems, costs, and things I would flag

1. **The offender-score weights are a judgement call with no calibration.** The
   `3×` on spills and the equal weighting of the other three terms are
   reasonable priors, not measured. Nothing has yet checked whether high-score
   shaders correlate with anything Metric 2 sees. Until that check exists, the
   score ranks candidates for inspection and must not be described as a severity
   measure. This is the one to fix with data, not code.
2. **The wave32/VOPD finding is still n = 1 game.** It reproduces cleanly
   (98.4% vs 0.0%) but on Remnant II alone — one vkd3d-translated,
   compute-heavy title. Metro EE is the opposite shape (102,393 graphics / 213
   compute). Until the corpus replay runs across several games grouped by
   `cohort` and `api`, the safe phrasing is: *"In one vkd3d-translated title,
   VOPD emission was confined to wave32 shaders, which were 1.4% of the
   sample."*
3. **`vopd_ratio` divides by VALU, which is a choice, not a fact.** VOPD per
   *instruction* would give a different denominator and a different ranking.
   VALU was chosen because dual-issue pairs are VALU operations, so it measures
   "of the work that could have been paired, how much was" — but this should be
   stated wherever the number appears.
4. **`mine.py` writes the full ranked table to `offenders.csv` every run**,
   which for the merged corpus is 17k+ rows — the top-N is only what gets
   returned for display. Harmless, but the file name implies a shortlist.
5. **`isa.py` covers only what was disassembled.** Disassembly is per-shader and
   slow, so it runs on the top-N offenders — which means ISA metrics describe a
   biased sample by construction (the worst shaders), never the corpus. Say
   "of the 25 ranked offenders" wherever those numbers appear.
6. **`chart.py` embeds the whole table in the HTML** — 2.1 MB for 17,736 rows.
   Fine locally; it is not something to attach to an email, and above ~20,000
   rows it truncates to the worst-scoring rows rather than the first N.

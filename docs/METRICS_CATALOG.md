# Metrics Catalog — what to measure, why it matters, and exactly how to get it

Companion to [METRICS_PLAN.md](METRICS_PLAN.md) (Metrics 1 & 2) and
[SHADERBENCH_PLAN.md](SHADERBENCH_PLAN.md) (Metric 3). Those two say *how the measurement loop
is built*; this says *which numbers go into it and where each one comes from*.

Every entry follows the same rule:

> **METRIC** → **why it matters** → **how we get it** (concrete, command-level)

Status tags:
✅ verified working on this machine ·
🟡 available but not yet wired ·
❌ needs code that does not exist yet ·
⚠️ needs a tool we do not have.

**Verified on 2026-07-28** (so nothing below is assumed):
- `fossilize-replay --enable-pipeline-stats` → 17,730 tidy rows from Remnant II in **38 s**.
- `fossilize-disasm --target isa` → emits **three** representations (NIR, ACO IR, Final Assembly)
with `s_delay_alu` operands fully decoded. This resolves PLAN.md §8 risk 2.
- `RADV_PERFTEST=cswave32,pswave32,gewave32` exist in `lib/mesa/src/amd/vulkan/radv_instance.c:107-112`.
- Wave-size reality: **98.6% of Remnant II shaders are wave64; VOPD appears in 0 of them.**

---

## 0. The two data sources, and what each can and cannot give

| source | cost | gives | cannot give |
|---|---|---|---|
| `fossilize-replay --enable-pipeline-stats` | ~38 s / 13k pipelines, whole corpus | per-stage counters: VGPR/SGPR/spills/code size/LDS/scratch/max waves, VALU/SALU/VMEM/SMEM/VOPD, instructions, ACO latency + inverse throughput, clauses, pre-sched pressure, **subgroup size**, **PSO/stage compile ns** | anything needing instruction *order* — hazards, dual-issue opportunity, clause structure |
| `fossilize-disasm --target isa` | seconds **per shader** | full text: NIR, ACO IR, Final Assembly with hex encodings | scales badly — top-N shaders only, never the corpus |

The split matters: **counters are free and complete; instruction-level analysis is expensive
and must be sampled.** Every metric below is placed on one side or the other deliberately.

---

## 1. `s_delay_alu` density and modelled stall cost ❌

**Metric.** Per shader: count of `s_delay_alu`, density (`s_delay_alu / VALU`), the
distribution of dependency classes (`VALU_DEP_1..4`, `SALU_CYCLE_1..3`, `TRANS32_DEP_*`), the
`instskip` distribution, and a **modelled stall-cycle total** = Σ (cycles implied by each
dependency class).

**Why it matters.** This is hypothesis #1 and it currently has *no metric anywhere in the
project*. RDNA3 removed the hardware interlocks that RDNA2 used to resolve register
dependencies, and made the **compiler** responsible for inserting explicit waits. If ACO is
conservative — inserting more waits, or longer ones, than the hardware actually needs — those
are cycles RDNA2 would have hidden for free and RDNA3 spends. That is a direct, mechanical
explanation for gen-over-gen gains varying by shader. Without this number, the s_delay_alu
hypothesis is a story, not a measurement.

**How we get it.**

1. Pick targets — this is a per-shader ISA pass, so rank first with the free counters:
   ```bash
   tcc mine --session <id> --top 200        # offender ranking from stats
   ```
2. Get the pipeline hashes to disassemble (`--tag 7` compute, `--tag 6` graphics):
   ```bash
   build/install/bin/fossilize-list data/foz/<game>/<db>.foz --tag 7 | head -200
   ```
3. Disassemble **under a chosen compiler** — the ISA is what that driver emitted, so the ICD
   selects which compiler you are measuring:
   ```bash
   VK_ICD_FILENAMES=$PWD/build/install/share/vulkan/icd.d/radeon_icd.x86_64.json \
   RADV_DEBUG=nocache \
   build/install/bin/fossilize-disasm data/foz/<game>/<db>.foz \
       --target isa --filter-compute <hash> --output <DIR>       # --output must be a DIRECTORY
   ```
   Output file: `<module>.<entry>.<pipeline>.comp`, containing three `Representation:` blocks.
   **Parse only the `Representation: Assembly (Final Assembly)` section** — the NIR and ACO IR
   blocks above it also contain instruction-like text and will corrupt counts if included.
4. Parse each assembly line. Verified real forms:
   ```
   s_delay_alu instid0(VALU_DEP_1)
   s_delay_alu instid0(SALU_CYCLE_1)
   s_delay_alu instid0(SALU_CYCLE_1) | instskip(SKIP_4) | instid1(VALU_DEP_1)
   ```
   Regex the three fields (`instid0`, `instskip`, `instid1`); one `s_delay_alu` can encode
   **two** waits, so count dependencies, not instructions.
5. Map each dependency class to cycles using the **RDNA3 ISA reference in `pdf_context/`** —
   do not hardcode guessed numbers; cite the table. Sum to a modelled stall total, and
   normalize by total instructions to get a comparable density.
6. **Validate the model against reality**: the modelled stall cost is a static proxy. Regress
   it against Metric 3 measured GPU time for the same shaders. If it does not correlate, say
   so — a proxy that fails validation is a finding, not something to bury.

**Code needed:** `analysis/isa.py` (disasm driver + assembly-section extractor) and
`analysis/hazards.py` (classification + cycle model). The formula names `stall_ratio` and
`vopd_ratio` from `_attic/prototypes/triage.py` are cited in the thesis — recover them with
`git show a7f0d75:_attic/prototypes/triage.py`.

**Reality check from the sample shader** (`00425b93a4329868`, Remnant II compute):
142 `s_delay_alu`, 281 `s_waitcnt`, 619 `v_fma_`, 3 `s_nop`, 0 `v_dual_`.

---

## 2. Wave size (wave32 vs wave64) 🟡

**Metric.** `subgroup_size` ∈ {32, 64} per stage, and the corpus-wide distribution per game
and per stage.

**Why it matters.** **This is the most important missing metric in the project.** Measured on
Remnant II:

```
wave64: 17,482 shaders (98.6%)  →  VOPD in     0  (0.0%)
wave32:    248 shaders ( 1.4%)  →  VOPD in   244 (98.4%)
```

VOPD (`v_dual_*`) is only encodable in wave32. So the entire "VOPD underuse" hypothesis is
really a **wave-size selection** question: ACO is not failing to find dual-issue pairs — it is
choosing wave64, where dual-issue is unavailable by construction. When it picks wave32 it
emits VOPD 98.4% of the time. Wave size also changes occupancy accounting, divergence cost,
and VGPR allocation granularity, so it confounds *every other metric* if left uncontrolled.

**How we get it.** Already in the data, for free:

1. The raw Fossilize CSV has a `Subgroup size` column, currently landing in the `extra` JSON
   blob. Promote it in `analysis/stats.py::_classify_column` (one line, same as the M1-A batch).
2. Add it as a **grouping key** everywhere: `compare.py` aggregates, `mine.py` ranking, and the
   ledger. Any VOPD statistic not conditioned on wave size is misleading.
3. **The experiment this unlocks** — force wave32 and re-measure. Verified flags:
   ```bash
   RADV_PERFTEST=cswave32,pswave32,gewave32 RADV_DEBUG=nocache \
   VK_ICD_FILENAMES=<stock icd> \
   build/install/bin/fossilize-replay --enable-pipeline-stats out.csv <db>.foz
   ```
   Then `tcc compare --a wave64_default --b wave32_forced`. This is a **real A/B with a real
   independent variable**, unlike stock-vs-custom which is currently null by construction.
   Expected: VOPD rises sharply, VGPR pressure and occupancy shift. Whether it gets *faster* is
   exactly what Metric 3 exists to answer.

---

## 3. VOPD capture rate and dual-issue ceiling 🟡 / ❌

**Metric.** Two numbers: **capture rate** = `vopd / valu` (free), and **ceiling** = how many
adjacent VALU pairs were *legally dual-issuable* but were not emitted as `v_dual_*` (ISA pass).
Underuse = ceiling − captured.

**Why it matters.** A raw VOPD count is confounded by shader size — a big shader has more of
everything. Worse, "underuse" is unfalsifiable without a denominator: 0 VOPD is a failure only
if dual-issue was *possible*. The ceiling turns a complaint into a measurement.

**How we get it.**

- **Capture rate** 🟡: pure derivation from promoted columns, `vopd / valu`, conditioned on
  wave size (§2). In wave64 it is identically zero and must be excluded, not averaged in.
- **Ceiling** ❌: requires the assembly section (§1 step 3). Walk consecutive VALU
  instructions and test each adjacent pair against the RDNA3 VOPD legality rules from
  `pdf_context/`: opcode must be in the dual-issue subset, the two halves must not conflict on
  VGPR banks, source/destination parity constraints, and wave32 only. Count legal pairs, then
  compare against emitted `v_dual_*`.
  - **Caveat to state in the thesis:** a pair being *legal* does not mean ACO could have
    scheduled it there without hurting something else (register pressure, latency hiding). The
    ceiling is an upper bound on opportunity, not a claim of lost performance.

---

## 4. Occupancy limiter attribution 🟡

**Metric.** For each shader: which resource caps waves/SIMD — **VGPR, SGPR, LDS, or scratch** —
plus the **headroom** to the next occupancy step (e.g. "4 VGPRs from 6→7 waves").

**Why it matters.** `max_waves` alone tells you occupancy is low but not *why*, which makes it
unactionable. "Reduce VGPRs" buys exactly nothing on an LDS-limited shader. The thesis claim
you actually want — "low-gain shaders are VGPR-limited at a rate of X% versus Y% for high-gain"
— requires attribution, not a scalar. Headroom additionally identifies the shaders where a
*small* compiler improvement would cross an occupancy threshold, which is where a compiler
change can produce a step change instead of a rounding error.

**How we get it.** Derived from columns already collected — no new capture:

1. Read the **gfx1101 (Navi 32, RDNA3)** resource limits from the ISA reference in
   `pdf_context/`: VGPR file size per SIMD, allocation granularity, SGPR allocation, LDS per
   workgroup, max waves per SIMD. Wave32 and wave64 have **different** VGPR accounting — §2 is
   a hard prerequisite.
2. Compute `waves_by_vgpr`, `waves_by_sgpr`, `waves_by_lds`, `waves_by_scratch`.
3. `limiter = argmin(...)`, `headroom = ` resource units needed to reach the next wave count.
4. **Self-check, and this is the important step:** `min(...)` must equal the driver-reported
   `max_waves` for every row. Any mismatch means the hardware model is wrong — fix the model
   before publishing any occupancy claim. This validation is free and catches exactly the class
   of error (wrong chip constants, e.g. the old gfx1100-vs-gfx1101 mixup) that would silently
   invalidate a whole chapter.

---

## 5. Normalized ratios (the confound fix) 🟡

**Metric.** `vmem/valu`, `valu/salu`, `instructions/code_size`, `vgprs/instructions`,
`spilled_vgprs/vgprs`, `latency/instructions`, `branches/instructions`.

**Why it matters.** Every counter currently collected is an **absolute count**, and absolute
counts are dominated by shader size. Correlate them against anything and the strongest signal
you find will be "big shaders are big". Ratios expose *character* instead of magnitude, and
character is what the thesis is about — a memory-bound shader and an ALU-bound shader of equal
size respond to a compiler change in opposite ways.

**How we get it.** Pure pandas derivation over the existing tidy table; zero capture cost.
Add as computed columns in `analysis/stats.py` after parsing, so `compare.py`, `mine.py` and
the ledger all see them. Guard every denominator against zero (many stages have `valu = 0`) and
emit `NaN`, never `0`, so they drop out of aggregates instead of biasing them toward zero.

---

## 6. Bottleneck taxonomy 🟡

**Metric.** One categorical label per shader: `alu-bound`, `memory-bound`, `branch-heavy`,
`lds-heavy`, `register-starved`, `trivial`.

**Why it matters.** This is the **independent variable of the entire thesis**. "Which workload
characteristics correlate with high vs low gains" is unanswerable until workloads are
*characterized*. Neither plan document defines a taxonomy, so today there is nothing to
correlate gains *against* except raw counters.

**How we get it.**

1. **Rule-based first**, built on §5 ratios with thresholds documented in `config/tcc.toml` so
   they are tunable and their provenance is recorded per run. Prefer rules over clustering: a
   thesis needs interpretable classes, and a reviewer can argue with a threshold but not with a
   k-means seed.
2. Calibrate the thresholds on the distribution of the whole corpus (quantiles), not on
   hand-picked constants.
3. **Validate the taxonomy against Metric 3**: shaders in different classes should respond
   *differently* to the same compiler change. If every class responds identically, the taxonomy
   carries no information and should be reported as such rather than kept for decoration.
4. Optional cross-check: k-means on the standardized ratio vector; agreement with the rule
   labels is evidence the classes are real structure and not an artifact of chosen cutoffs.

---

## 7. Gen-over-gen delta — the missing dependent variable ⚠️

**Metric.** For the same shader: static compiler output for an **RDNA2** target (gfx1030/1031/1032)
versus **RDNA3** gfx1101 — VGPR count, occupancy, instruction count, and what RDNA3-only
constructs (`s_delay_alu`, `v_dual_*`) appear.

**Why it matters.** This is the largest structural gap in the project. The thesis is about
*gen-over-gen* behaviour, but there is **no RDNA2 hardware** and **no measurement of gain
anywhere in the pipeline**. The `cohort = "high-gain" / "low-gain"` fields in the game TOMLs are
hand-written labels with no recorded source and no validation — an unmeasured dependent
variable that every later correlation silently rests on.

**How we get it.** Two honest options; they answer *different* questions and the difference must
be stated explicitly:

- **(a) Static cross-architecture compile — measurable here.** ⚠️ needs the AMD **RGA** tarball
  (still not downloaded; `tools/rga/`). RGA compiles the same input offline for multiple ASIC
  targets and reports ISA plus resource usage per target.
  1. Extract SPIR-V per module from the foz:
     ```bash
     build/install/bin/fossilize-disasm <db>.foz --target asm --module-only \
         --filter-module <hash> --output <DIR>     # SPIR-V assembly text
     spirv-as <DIR>/<hash> -o shader.spv           # /usr/bin/spirv-as, verified present
     ```
  2. Compile for both generations and diff resource usage:
     ```bash
     rga -s vk-spv-offline --asic gfx1030 --asic gfx1101 --isa isa.txt \
         --livereg live.txt -c shader.spv
     ```
  3. **What this legitimately claims:** how the compiler's *output* differs per architecture for
     identical source. **What it does not claim:** an FPS gain. It is a compiler/ISA comparison,
     not a hardware benchmark. Never present it as a measured generational speedup.
- **(b) Published benchmark data as an explicit external input.** If cohort labels come from
  reviews, then record the source, date, resolution, settings and driver version per game in
  the TOML, and treat it as cited external evidence with its own error bars — not as data you
  measured.

Doing neither leaves the thesis correlating against labels nobody can defend.

---

## 8. Compile time / shader stutter 🟡

**Metric.** Per pipeline: `PSO duration (ns)`, `PSO wall duration (ns)`, `Stage duration (ns)`.
Aggregated: total corpus compile time, p99 per-pipeline compile time, and the stock-vs-custom
delta.

**Why it matters.** METRICS_PLAN calls this a "bonus axis" and never defines it — while the
three columns are **already sitting in every row you have collected**, unused. Compilation cost
drives traversal hitching and shader-comp stutter, a genuine RDNA3-era complaint that
steady-state FPS completely hides. It is also a direct compiler-quality axis in its own right: a
compiler that produces 2% better code but compiles 50% slower is a bad trade for a game that
compiles pipelines during play.

**How we get it.**
1. Promote the three keys out of `extra` (same one-line change as §2).
2. Aggregate per game and per driver; report p50/p99 and the total.
3. **Controls that make the number mean anything:** fix `--num-threads` (it changes wall
   duration directly), always run with `RADV_DEBUG=nocache` so nothing is served from cache, and
   record both in the run manifest.
4. **Keep it strictly separate from the FPS calibration.** Compile time explains *stutter*, not
   steady-state frame cost; letting it leak into the static→FPS model would corrupt both.

---

## 9. Shaderbench: dose-response and canary ❌

**Metric.** Per shader, two timings at different invocation budgets → **slope** (per-invocation
cost) and **intercept** (fixed launch/setup overhead). Plus a **canary**: one trivial authored
shader timed at intervals throughout every run.

**Why it matters.** The current design measures one point per shader, which conflates
per-invocation cost with dispatch overhead. A compiler change that improves the shader *body*
looks diluted by a constant, and worse, the dilution differs per shader — so the ranking of
"which shaders improved" is distorted. Two points separate the two effects for roughly double
the runtime. The canary is independent insurance: the §"drift tripwire" in SHADERBENCH_PLAN
catches drift *between* runs, but nothing currently catches a thermal event *during* a run.

**How we get it.**
1. Run each pipeline at budget `N` and `4N` (SHADERBENCH_PLAN §3.2 already fixes an invocation
   budget; add a second multiplier).
2. `slope = (t_4N − t_N) / (3N)`, `intercept = t_N − slope·N`. Report both; use **slope** as the
   compiler-quality signal and watch intercept as a validity check — it should be roughly
   constant across shaders, and if it is not, the harness is measuring something else.
3. Canary: a fixed trivial compute shader, dispatched every K pipelines, its timing recorded
   into `run.json`. If canary time drifts more than the noise band during a run, flag the whole
   run `thermally_suspect` rather than silently accepting it.

---

## 10. Statistical heuristics ❌

**Metrics/procedures.** False-discovery-rate control, clustered inference, effect sizes with
confidence intervals, and validation of the offender score.

**Why it matters.**
- You will test ~18 metrics across ~18 games. At α=0.05 that is a near-certainty of spurious
  "significant" findings. Uncorrected p-values in a thesis defense is an easy kill shot.
- **Per-shader rows are not independent.** Millions of rows nested inside 18 games does not give
  n = millions; for any *game-level* claim the effective n is **18**. Treating shaders as
  independent samples inflates significance enormously.
- The offender score `z(vgpr) + z(−waves) + z(code_size) + 3·z(spill)` has **never been
  validated** — the weight of 3 on spills is a guess, and everything downstream (corpus
  selection, top-N ISA analysis) inherits that guess.

**How we get it.**
1. **FDR**: Benjamini–Hochberg over the family of metric tests; report q-values, not raw p.
   Implementable in ~20 lines with numpy — no new dependency needed.
2. **Clustering**: report game-level effects with game as the unit, or use a mixed-effects model
   with a random intercept per game. If that means adding `statsmodels`, add it deliberately and
   record why (`networkx` was just removed for being an undeclared-but-unused dependency — do
   not repeat that).
3. **Effect sizes with bootstrap CIs** rather than significance stars; with this much data,
   everything will be "significant" and nothing will be *large*.
4. **Validate the offender score**: Spearman rank correlation between the score and Metric 3
   measured GPU time. If it does not predict, re-fit the weights against measured time instead
   of defending an arbitrary formula. This is now possible for the first time — before Metric 3
   there was nothing to validate against.

---

## Ordering (cheapest evidence first)

| # | metric | effort | blocked by |
|---|---|---|---|
| 2 | wave size | one line (promote) | — |
| 8 | compile time | one line (promote) | — |
| 5 | ratios | pandas derivation | — |
| 3a | VOPD capture rate | pandas derivation | §2 |
| 4 | occupancy limiter | model + self-check | §2, ISA PDF constants |
| 6 | taxonomy | rules on §5 | §5 |
| 1 | s_delay_alu | `isa.py` + `hazards.py` | ISA parse (✅ verified working) |
| 3b | VOPD ceiling | pair-legality pass | §1 parser |
| 10 | statistics | analysis layer | data from the above |
| 9 | dose-response + canary | harness change | SB-0/SB-3 |
| 7 | gen-over-gen | ⚠️ RGA download | external tool |

The first four are effectively free and turn the two currently-unmeasured hypotheses into
numbers. §7 is the one that decides whether the thesis has a defensible dependent variable at
all, and it should be settled before more infrastructure is built on top of the current
cohort labels.

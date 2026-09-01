# Arm 2 — Directed microbenchmarking and compiler architecture

Companion to [ARM1_CORPUS.md](ARM1_CORPUS.md). Arm 1 measures *what production
shaders do*. Arm 2 asks *why the compiler produced that code*, and what the
hardware would have done with better code.

- **Updated:** 2026-08-21 · derived from the Mesa tree at `lib/mesa`
  (`git describe` head `6e3d8057357`)
- **Claim classes** follow [RESEARCH_GUIDELINES.md](RESEARCH_GUIDELINES.md):
  🟩 verified at source · 🟨 located, not read at source · 🟥 derived/inferred here

---

## 1. Why this arm exists

Arm 1 can only ever produce a correlation: *shaders with property P run slower*.
It cannot say whether P is a hardware limit or a compiler decision, because in a
production shader every variable moves at once — register pressure, memory
traffic, wave size, control flow.

Arm 2 separates them two ways:

1. **Microbenchmarks** hold everything constant but one variable, so a
   penalty curve can be attributed to a cause.
2. **Compiler-architecture analysis** reads the passes that made the decision
   and, where an ablation switch exists, turns each one off and re-measures.

The second half is what makes this arm cheap. **Every pass that matters to this
thesis already has a documented off-switch in ACO.** No compiler modification is
required to obtain the first round of causal results — see §4.

---

## 2. The ACO pipeline, read at the source

🟩 **Verified** in [`lib/mesa/src/amd/compiler/aco_interface.cpp:100-180`](../lib/mesa/src/amd/compiler/aco_interface.cpp).
Order is the execution order; the RA line is the axis this whole arm turns on.

| # | Pass | File | Gate |
|---|---|---|---|
| 1 | `live_var_analysis` | `aco_live_var_analysis.cpp` | always |
| 2 | `spill` | `aco_spill.cpp` | always |
| 3 | `schedule_program` | `aco_scheduler.cpp` | `!DEBUG_NO_SCHED` |
| **4** | **`register_allocation`** | `aco_register_allocation.cpp` | **always** |
| 5 | `optimize_postRA` | `aco_optimizer_postRA.cpp` | `!DEBUG_NO_OPT` |
| 6 | `ssa_elimination` → `lower_to_hw_instr` → `lower_branches` | — | always |
| **7** | **`schedule_vopd`** | `aco_scheduler_ilp.cpp` | `!DEBUG_NO_SCHED_VOPD` |
| 8 | `schedule_ilp` | `aco_scheduler_ilp.cpp` | `!DEBUG_NO_SCHED_ILP` |
| 9 | `insert_waitcnt` → `insert_NOPs` | — | always |
| 10 | `insert_delay_alu` | `aco_insert_delay_alu.cpp` | `gfx_level >= GFX11` |
| 11 | `form_hard_clauses` | `aco_form_hard_clauses.cpp` | `gfx_level >= GFX10` |
| 12 | `combine_delay_alu` | `aco_insert_delay_alu.cpp` | `gfx_level >= GFX11` |

### 2.1 The central finding: register allocation is VOPD-blind

🟩 `schedule_vopd` runs at step **7**, three steps *after* register allocation
and after lowering to hardware instructions. 🟩 `aco_register_allocation.cpp`
contains **zero** occurrences of the string `vopd`, case-insensitive.

The consequence is structural, not incidental:

> VOPD legality on RDNA3 is decided almost entirely by *which physical VGPRs the
> operands landed in* — the 4-bank source rules and the even/odd destination
> rule (ISA §7.6). The pass that assigns those physical registers does not know
> VOPD exists. The pass that needs the assignment to come out a particular way
> runs after it and cannot change it.

Every VOPD pair that fails on a bank conflict therefore fails by **accident of
allocation**, not by a decision anyone made. 🟥 This is the single strongest
"compiler leaves performance on the table" claim available in this project, and
unlike the NVIDIA literature it is checkable against an open source tree.

**Direct precedent.** This is exactly the gap Scott Gray's Maxas exploited on
Maxwell: its headline capability was hand-assigning registers to avoid 4-bank
conflicts that `ptxas` allocated into. The RDNA3 situation is the same shape —
a bank-constrained dual-issue path fed by a bank-unaware allocator — with the
difference that here the allocator is 20k lines of readable MIT-licensed C++.

### 2.2 VOPD pairing is a 16-instruction peephole

🟩 `aco_scheduler_ilp.cpp:27`: `constexpr unsigned num_nodes = 16;` — the
scheduler maintains a partial DAG of at most 16 nodes, and `mask_t` is a
`uint16_t` sized to it. 🟩 The file header states only ALU instructions are
freely scheduled; memory loads stay in order and everything else is not
reordered at all.

🟥 **Testable consequence:** two VOPD-pairable VALU instructions separated by
more than 16 reorderable instructions can never be paired, regardless of
legality. This is a hard, quantifiable compiler horizon. It becomes experiment
E2.1.

### 2.3 The legality test, and its escape hatch

🟩 `is_vopd_compatible` (`aco_scheduler_ilp.cpp:265-302`) rejects a pair when:

1. neither op can be OPX, **or** both destinations have the same parity;
2. both carry a literal and the literals differ;
3. source VGPR banks are incompatible (`are_src_banks_compatible`).

If (3) fails it retries **once** with the operands of a commutative op swapped,
and marks the pair `vopd_need_swap`. 🟩 Swapping `v_dual_mov_b32` demotes it to
OPY-only. `can_use_vopd` (`:305-350`) then rejects WaW and RaW pairs; 🟩 **WaR is
only checked on GFX12+**, quoting the RDNA4 ISA — RDNA3 hardware tolerates it.

🟥 So ACO already has one bank-conflict repair mechanism (commutative swap) and
it is the *only* one. There is no re-allocation, no copy insertion, no second
attempt. That bounds how much of §2.1's accident the compiler can recover.

### 2.4 `s_delay_alu`: representable range and the packing pass

🟩 `alu_delay_info` (`aco_insert_delay_alu.cpp:31-52`) caps what can be
expressed: `valu_nop = 5`, `trans_nop = 4` — i.e. a dependency further back than
**4 VALU** or **3 transcendental** instructions is not representable and the
wait degenerates to a no-op.

🟩 `combine_delay_alu` (`:366-392`) merges two `s_delay_alu` into one using the
skip field: `imm |= (skip << 4) | (imm << 7)`, bailing when `skip >= 6`. This
**independently corroborates the encoding correction in
[STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §1.1** — `INSTID0[3:0]`,
`INSTSKIP[6:4]`, `INSTID1[10:7]`, skip range 0–5 — from the Mesa tree rather
than from the ISA PDF. Two independent sources now agree, and the retired
`outdated_research.md` bitfield is wrong against both.

### 2.5 ACO's own admission of Hardwall 1

🟩 `aco_insert_delay_alu.cpp:19-29`, verbatim:

> *"Note that if we do not emit s_delay_alu things will still be correct, but the
> wave will stall in the ALU (and the ALU will be doing nothing else). We'll use
> this as I'm pretty sure our cycle info is wrong at times (necessarily so, e.g.
> wave64 VALU instructions can take a different number of cycles based on the
> exec mask)"*

This is the divergence hardwall stated by the implementer, not inferred by us,
and it is the best single quote this thesis has.

---

## 3. What this adds to the existing literature

| Prior work | What it established | What Arm 2 adds |
|---|---|---|
| Maxas (Gray 2014), KeplerAs / Zhang PPoPP'17, CuAssembler | Hand-scheduling SASS beats `ptxas`; register bank conflicts are the recurring culprit | Same failure mode on an **open** compiler, so the cause is readable instead of reverse-engineered |
| CuAsmRL (He & Yoneki, CGO'25) | 9% mean / 26% max over `-O3` SASS on A100 — but the action space is **memory** load/store reordering only | Measures the **ALU-side** headroom (VOPD + delay), which CuAsmRL deliberately does not touch |
| Huerta et al. 2025 | Control codes cost 0.09% of RF area vs 5.32% for a scoreboard | Supplies the *other* half of the trade: what the software side pays back in lost issue slots |
| Chips and Cheese 2023 | RDNA3 dual-issue reaches peak only on ideal FP32 add/FMA; blames bank conflicts and scheduling distance | Turns "blames" into a measured attribution: ablate the pass, re-measure, see if the gap moves |
| Wong et al. ISPASS'10 and lineage | The microbenchmarking method itself | Applies it to RDNA3 with the compiler as an **independent variable**, not a fixed black box |

🟥 **Honest scoping of CuAsmRL.** Read at the source (arXiv:2501.08071v1): the
RL action space is restricted to swapping `LDG`/`LDGSTS`/`STG` with adjacent
instructions. Citing its 9% as evidence that *ALU* scheduling leaves 9% on the
table would be an overclaim. What it legitimately supports is narrower and still
useful: on hardware where the compiler owns the schedule, a *single* class of
reordering left ~9% unclaimed after `-O3`.

### 3.1 The trajectory argument got stronger

🟩 LLVM PR **#147826** (Stanislav Mekhanoshin, 2025-07-09) adds MC and
disassembler tests for **`gfx1250_asm_vopd3.s`** — a third VOPD encoding.
🟨 Secondary reporting (Tom's Hardware, Chips and Cheese) states VOPD3 permits
X and Y to read the **same input VGPRs**, relaxing exactly the operand-supply
constraint this thesis measures. *Not yet verified against the LLVM defs — do
not cite the "same VGPR" claim as fact until `AMDGPUInstrInfo`/`VOP3Instructions.td`
for gfx1250 is read.*

🟥 If it holds, the narrative closes cleanly: RDNA3 pushed pairing onto the
compiler under bank rules the allocator cannot see; RDNA4 kept the mechanism and
tightened WaR; RDNA5 relaxes the operand rule that made pairing hard. The thesis
measures the generation where the cost was highest.

---

## 4. Experiments

Ordered by cost. E2.0–E2.2 need **no compiler modification and no new code** —
they reuse the Arm 1 machinery with a different environment variable.

### ✅ E2.0 — Fix and validate the ablation profiles — **DONE 2026-08-21**

Fixed, and **the knob was proven to bite**. Result in §5.



🟩 **`config/profiles/stock-novopd.toml` does not do what it says.** It sets
`RADV_DEBUG=novopd`. The string `novopd` **does not exist anywhere in the Mesa
tree** — not in `radv_debug_options[]` (`radv_instance.c:30-90`), not anywhere
under `src/amd/`. 🟩 `parse_debug_string` (`src/util/u_debug.c:420-443`)
silently ignores unrecognised tokens: no warning, no error, zero flags set.

The profile is a **no-op that produces a null delta**. Had it been run as-is,
the result would have read as "disabling VOPD changes nothing" and would have
been wrong. The correct knob is `ACO_DEBUG=nosched-vopd`.

🟩 The real switches (`aco_ir.cpp:25-39`, parsed from `ACO_DEBUG` via
`os_get_option`, active in release builds):

| Token | Disables |
|---|---|
| `nosched-vopd` | VOPD pair formation only |
| `nosched-ilp` | post-RA ILP/clause scheduler only |
| `nosched` | pre-RA scheduler **and** both post-RA schedulers |
| `noopt` | `optimize_postRA` |
| `novn` | value numbering |
| `perfinfo` | *enables* per-shader performance info output |

✅ **Done 2026-08-21.** `stock-novopd.toml` now sets `ACO_DEBUG=nosched-vopd` in
`[env]`; `stock-nosched-ilp.toml` and `stock-nosched.toml` added; all six
profiles verified to compute the intended environment through
`config.profile_env()`. The knob was then proven to bite — §5.

🔴 **A second dead variable, found by the same audit and fixed.**
`src/core/config.py` set `RADV_THREAD_TRACE_TRIGGER` for SQTT capture. 🟩 That
name exists **nowhere** in the Mesa tree. SQTT moved to the shared Vulkan
runtime: `MESA_VK_TRACE_TRIGGER` (`src/vulkan/runtime/vk_instance.c:210`), and
the tracer must also be armed with `MESA_VK_TRACE=rgp`. The `capture-sqtt`
profile would have produced no trace and no error. Both variables are now set.

**Standing rule this establishes:** a profile that cannot be shown to change the
emitted code must never be used to produce a null result. Two of six profiles
were silently inert. The remaining ones — `custom`, `capture-rdc`,
`bench-mangohud` — have still not been audited this way.

### E2.1 — VOPD pairing horizon (tests the 16-node window)

Synthetic compute shader: two independent, VOPD-legal `v_fma_f32` chains
separated by *N* independent filler VALU ops, N ∈ {0,2,4,8,12,15,16,20,32}.
Compile with `--enable-pipeline-stats`, read the driver's `VOPD` counter.

**Predicted:** pairing rate collapses between N=15 and N=16. A clean step there
converts §2.2 from inference to measurement and gives the thesis a named
compiler constant. **If the step does not appear**, the window interacts with
something not yet understood — report that, do not bury it.

### E2.2 — Corpus-wide pass ablation *(highest value per hour)*

Replay the **existing 18-game corpus** under `stock`, `nosched-vopd`,
`nosched-ilp` and `nosched`. Compare per-shader instruction count, VOPD count,
VGPR count and `Inverse Throughput` from the driver statistics.

This answers, on real production shaders and with code that already works:
*how much does each ACO scheduling pass actually buy on RDNA3?* No published
number exists for this. 🟥 It is also the cheapest defensible result in the
whole project — the corpus, the replay path and the ledger are already built and
already passed their null tests.

### E2.3 — Bank-conflict cost

Pairs of VOPD-legal ops whose sources are deliberately allocated into
conflicting vs non-conflicting banks. Measures the penalty §2.1 says the
allocator is imposing blindly. Needs either post-RA inspection or a small ACO
patch to force placement — the first modification this project actually needs.

### E2.4 — `s_delay_alu` distance curve

Dependency distance 1–8 VALU, with and without the emitted `s_delay_alu`, timed
under M3. Maps the penalty curve and locates the point where §2.4's
`valu_nop = 5` cap makes the hint unrepresentable.

### E2.5 — Occupancy staircase

VGPR demand stepped across the 24-register granularity boundaries on gfx1101,
validating the derived table in [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §1.3
against the driver's own `Subgroups per SIMD`. Converts derived arithmetic into
measurement — flagged there as a known weakness.

### E2.6 — ACO versus LLVM on identical input

Same SPIR-V through ACO and through `RADV_DEBUG=llvm`, diffing `s_delay_alu`
density and VOPD rate. Two independent teams solving one ISA constraint; where
they disagree, at least one is leaving something on the table.

---

## 5. First measured result — VOPD ablation on *Sol Cesto* (2026-08-21)

The first Arm 2 number, obtained in under ten minutes with no new code. 🟩

**Method.** `data/foz/solcesto/steam_pipeline_cache.foz`, 158 graphics pipelines
→ **300 pipeline stages**, replayed three times through the stock local Mesa
build on the RX 7800 XT (gfx1101), cache-isolated per run:

```bash
ICD=build/install/share/vulkan/icd.d/radeon_icd.x86_64.json
FOZ=data/foz/solcesto/steam_pipeline_cache.foz

# A — driver default
VK_ICD_FILENAMES=$ICD RADV_DEBUG=nocache MESA_SHADER_CACHE_DIR=$D/a \
  build/install/bin/fossilize-replay --enable-pipeline-stats $D/a.csv "$FOZ"
# B — wave32 forced
... RADV_PERFTEST=cswave32,pswave32,gewave32 ...
# C — wave32 forced, VOPD pairing disabled
... RADV_PERFTEST=cswave32,pswave32,gewave32 ACO_DEBUG=nosched-vopd ...
```

Paired on `(Pipeline hash, Executable name)` — **300/300 stages matched, no
duplicate keys**. `Hash` cannot be the join key across an ablation: the shader
hash changes when the code changes, and joining on it silently drops every stage
the ablation affected (13 of 300 survive — a trap worth recording).

**Result.**

| | A: default | B: wave32 | C: wave32, no VOPD |
|---|---|---|---|
| Subgroup size | **64** on 300/300 | **32** on 300/300 | 32 on 300/300 |
| Stages with VOPD > 0 | **0** | **278 (92.7%)** | 0 |
| VOPD instructions | 0 | **2990** | 0 |
| VALU | 21698 | 18528 | 21518 |
| Modeled `Inverse Throughput` | 20365 | **30405** | 35386 |
| VGPRs (median / max) | 36 / 60 | 48 / 72 | 48 / 72 |

**1. The ablation switch works.** 2990 → 0. E2.0's acceptance criterion is met,
and both `stock-novopd` and `stock-wave32` are now trustworthy instruments.

**2. H2 holds on a second title, and more cleanly than on the first.** Under the
driver's own policy this game emits **zero** VOPD across all 300 stages. Force
wave32 and 92.7% of stages carry it. VOPD availability on RDNA3 is decided
**entirely by wave-size policy**, not by the compiler failing to find pairs.
Remnant II showed this at 98.6% wave64; solcesto shows it at 100%. 🟥 n = 2, both
single-vendor-driver, both graphics-only — still not a corpus claim.

**3. The counter identity holds exactly.** VALU falls by 21518 − 18528 = **2990**,
precisely the VOPD count. Each VOPD absorbs exactly one VALU slot, so the
driver's VOPD statistic can be read directly as "VALU instructions eliminated by
pairing" — **13.9% of the VALU stream**. This validates the counter's semantics,
which no document had pinned down.

**4. B vs C is the honest comparison, and VOPD wins it.** Same wave size, same
shaders, one pass toggled: modeled `Inverse Throughput` improves **14.08%** in
total, **median −9.92%** per stage, best −37.70%. 250 of 300 stages improve, 42
are unchanged, and **8 fragment stages get ~2% worse** — small, but evidence that
the pairing heuristic is not monotonically good.

### What this result does *not* show

- 🟥 **`Inverse Throughput` is ACO's static cost model, not a measurement.** The
  14.08% is what the compiler *believes*. Whether the GPU agrees is M3's job, and
  M3 has not been run on this. **Do not quote 14.08% as a speed-up.**
- 🟥 **A vs B is not apples to apples.** Wave32 needs twice the waves for the same
  work, so the default column's lower `Inverse Throughput` (20365) does not mean
  wave64 is faster. Comparing modeled cost across wave sizes is invalid; only
  B vs C is a controlled comparison.
- The wave32 gain is not free: median VGPRs rise 36 → 48, and reported waves/SIMD
  halve. Whether the occupancy cost exceeds the pairing gain is exactly what M3
  must decide.
- One game, 158 graphics pipelines, **zero compute pipelines**.

⚠️ **An unresolved discrepancy, recorded rather than explained.** The driver
reports `Subgroups per SIMD` = **32** for the wave64 stages (median 32, max 32),
but [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §4 item 5 states the maximum is
**16** on GFX10_3+, from `ac_gpu_info.c:245`. Either the statistic is not
per-SIMD-per-wave in the sense assumed, or that audit item is wrong. **This must
be resolved before any occupancy claim is made** — it sits underneath H3 and
under E2.5.

---

## Known problems, costs, and things I would flag

1. **§2.1 is an argument about code structure, not a measurement.** "RA is
   VOPD-blind" is verified; "therefore pairs are lost" is not, until E2.2 or
   E2.3 puts a number on it. The failure mode to guard against is stating the
   structural fact and letting the reader supply the magnitude.
2. **The 16-node window may not bind in practice.** If real shaders rarely have
   pairable ops more than 16 apart, E2.1 will show a real constant that explains
   nothing. That is a valid negative result and must be reported as one.
3. **E2.0 found one broken profile; the others were not audited.** `stock`,
   `custom`, `capture-sqtt`, `capture-rdc`, `bench-mangohud` and `stock-wave32`
   have not been checked against the driver's option tables the way
   `stock-novopd` just was. `cswave32`/`pswave32`/`gewave32` in particular need
   the same treatment before H2 is tested.
4. **Everything in §2 is one Mesa checkout at one commit.** ACO pass order is
   not ABI; a Mesa bump can move `schedule_vopd` relative to RA and silently
   invalidate §2.1. Pin the commit in the thesis and re-check before defense.
5. **No microbenchmark harness exists yet.** E2.1 and E2.3–E2.5 all depend on
   `shaderlab/harness/` (TODO Phase 5), which is not started. Arm 2's cheap
   half (E2.0, E2.2) is available now; the rest carries the schedule risk.
6. **VOPD3/RDNA5 is 🟨 and load-bearing for the trajectory argument.** One
   verified test-file commit, one unverified capability claim. Do not let it
   into the thesis until the LLVM instruction definitions are read directly.

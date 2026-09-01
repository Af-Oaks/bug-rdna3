# State of the art — compiler-managed hazards, and verified RDNA3 reference data

Two jobs in one file.

1. **Reference data verified at the primary source** — the RDNA3 encoding, pairing
   and occupancy facts, read out of AMD's manuals and out of the Mesa tree on this
   machine, with section numbers and file:line so any of it can be re-checked.
2. **The literature** on moving hazard resolution from hardware into the compiler,
   which is what gives this work a frame of reference and a defensible novelty claim.

§4 audits [`attic/outdated_research.md`](attic/outdated_research.md) against
§1–§2. That report is a useful map of the territory and **several of its
technical tables are wrong** — wrong enough to sink a chapter if copied. It was
**retired to [`attic/`](attic/README.md) on 2026-08-20** along with two
derivative files; nothing from any of them may be quoted, and §4 is the record of
why.

Feeds protocol step 1 in [METHODOLOGY.md](METHODOLOGY.md); references land in
[BIBLIOGRAPHY.md](BIBLIOGRAPHY.md); the argument they support is in
[PREMISE.md](PREMISE.md).

**Sources used here:** `pdf_context/rdna3-shader-instruction-set-architecture-feb-2023_0.pdf`
and `pdf_context/rdna2-shader-instruction-set-architecture.pdf` (extracted with
`pdftotext -layout`), and the local Mesa checkout under `lib/mesa/`.
⚠️ The Mesa tree is a development snapshot (26.1.0-devel) — **pin its commit hash
before citing any file:line in the dissertation.**

---

## 1. Primary-source reference data

### 1.1 `S_DELAY_ALU` — encoding

Format SOPP, opcode 7 (`0xBF87` as the high half-word). The payload is a 16-bit
immediate, and **only bits [10:0] are used**:

```
SIMM16 bit:  15 …  11 │ 10   9   8   7 │  6   5   4 │  3   2   1   0
                      │                │            │
             unused   │     INSTID1    │  INSTSKIP  │     INSTID0
                      │    (4 bits)    │  (3 bits)  │    (4 bits)
```

> `INSTID0 = SIMM16[3:0]` · `INSTSKIP = SIMM16[6:4]` · `INSTID1 = SIMM16[10:7]`
> — RDNA3 ISA §16.5

**`INSTID0` / `INSTID1` values** (§16.5, complete):

| value | symbol | meaning |
|---:|---|---|
| 0x0 | `INSTID_NO_DEP` | no dependency on any prior instruction |
| 0x1–0x4 | `INSTID_VALU_DEP_1..4` | depends on a VALU instruction 1–4 back |
| 0x5–0x7 | `INSTID_TRANS32_DEP_1..3` | depends on a TRANS32 instruction 1–3 back |
| 0x8 | `INSTID_FMA_ACCUM_CYCLE_1` | **reserved** — single-cycle FMA accumulation penalty |
| 0x9 | `INSTID_SALU_CYCLE_1` | 1-cycle penalty for a prior SALU instruction |
| 0xa–0xb | `INSTID_SALU_CYCLE_2..3` | **reserved** |

**`INSTSKIP` values** (§16.5, complete):

| value | symbol | meaning |
|---:|---|---|
| 0x0 | `INSTSKIP_SAME` | both dependencies apply to the same (next) instruction |
| 0x1 | `INSTSKIP_NEXT` | second dependency applies to the instruction after the next |
| 0x2–0x5 | `INSTSKIP_SKIP_1..4` | skip 1–4 instructions, then apply the second dependency |
| 0x6 | — | reserved |

⚠️ **The manual contradicts itself.** §5.7 Table 19 describes codes 5–7 as
*"dependent on previous trans. VALU **1-4** back"*, while §16.5 enumerates exactly
three symbols, `TRANS32_DEP_1..3`. §16.5 is the encoding section and matches the
value count, so it wins — but the discrepancy is worth a footnote in the
dissertation, and worth confirming against emitted code, which the bench can do
for free.

**Semantics that matter for H1** (§5.7, §16.5):

- Optional for correctness. *"Without them the program still functions correctly
  but performance may suffer when multiple waves are in flight."*
- May execute in **zero cycles**, in parallel with the preceding instruction.
- One `S_DELAY_ALU` can express **two** dependencies. Two consecutive ones cannot:
  *"the current S_DELAY_ALU replaces any previous dependency info."* **So counting
  instructions undercounts dependencies — count decoded fields, not opcodes.**
- Illegal inside an `S_CLAUSE` clause.
- `INSTID` counts backwards over *issued* VALU instructions, skipping those
  branched over, but **counting instructions skipped by `EXEC == 0`** — those are
  *"scoreboard immediately marked 'ready'"*.

### 1.2 VOPD — dual-issue pairing rules

§7.6, §15.3.7, §16.11. *"This instruction has certain restrictions that must be
met — hardware does not function correctly if they are not. This instruction
format is legal only for wave32. It must not be used by wave64's. It is skipped
for wave64."*

Constraints the compiler must satisfy for every emitted pair:

- **wave32 only**; no DPP; the two operations must be independent.
- Each operation may use up to 2 VGPRs.
- At most 2 SGPRs total, or 1 SGPR + 1 literal, or a shared literal.
- `SRC0` may be VGPR/SGPR/constant; `VSRC1` must be a VGPR.
- **4 VGPR banks**, indexed by `SRC[1:0]`, each with 3 read ports (one each for
  SRC0, SRC1, SRC2). `SRCX0` and `SRCY0` must use **different banks**; likewise
  `VSRCX1` and `VSRCY1`. `FMAMK` is an exception — its "S1" uses the SRC2 port.
- If both operations use SRC2, one index must be even and the other odd.
- Destination VGPRs: one even, one odd (`vdstY` encodes bits [7:1]; the low bit is
  `!vdstX[0]`).

**Opcode sets** (Tables 91 and 92 — the X and Y sides are *not* the same):

| side | opcodes |
|---|---|
| **X** (14) | `FMAC_F32`, `FMAAK_F32`, `FMAMK_F32`, `MUL_F32`, `ADD_F32`, `SUB_F32`, `SUBREV_F32`, `MUL_DX9_ZERO_F32`, `MOV_B32`, `CNDMASK_B32`, `MAX_F32`, `MIN_F32`, `DOT2ACC_F32_F16`, `DOT2ACC_F32_BF16` |
| **Y** (17) | the same 14, **plus** `ADD_NC_U32`, `LSHLREV_B32`, `AND_B32` |

All prefixed `V_DUAL_`. The asymmetry matters: the three integer/shift operations
exist **only on the Y side**, so a legal pair cannot be formed from two of them.
Any VOPD-ceiling analysis that assumes a symmetric opcode set will overcount
opportunity.

### 1.3 Register file and occupancy — gfx1101 (Navi 32)

From the ISA and from `lib/mesa/src/amd/common/ac_gpu_info.c`:

| quantity | value | source |
|---|---|---|
| max waves per SIMD | **16** (GFX10_3 and later; RDNA1 was 20) | `ac_gpu_info.c:245-246` |
| physical VGPRs per SIMD | **768 wave64 → 1536 wave32** for Navi 31 / Navi 32 | `ac_gpu_info.c:288-290` |
| VGPR allocation granularity | 24 (wave32) / 12 (wave64) on a 1536-VGPR device | ISA §3.3.2.1; `ac_gpu_info.c:297` |
| max VGPRs per shader | 256 | ISA §3.3.2.1 |
| SGPRs per wave | 106 normal + VCC (s106–107) + 16 trap-temp | ISA §3.3.1.1 |
| SGPR allocation | **fixed block of 108**, 108 × 16 per SIMD | `ac_gpu_info.c:255-258` |

Two consequences the popular tables get wrong:

**SGPRs cannot limit occupancy on RDNA.** Allocation granularity, minimum and
maximum are all 108, and the SIMD holds `108 × max_waves`. Any occupancy model
carrying an SGPR term is carrying a term that can never bind. Model VGPR, LDS and
scratch; report SGPR as informational.

**The occupancy cliff starts at 96 VGPRs, not at 64.** For wave32 on Navi 32:

```
waves_per_simd = min( 16 , floor( 1536 / (ceil(vgprs / 24) * 24) ) )
```

| VGPRs used | allocated | waves/SIMD |
|---:|---:|---:|
| ≤ 96 | ≤ 96 | **16 (full)** |
| 120 | 120 | 12 |
| 144 | 144 | 10 |
| 168 | 168 | 9 |
| 192 | 192 | 8 |
| 240 | 240 | 6 |

⚠️ **Derived, not measured.** Mesa prefers the kernel-reported VGPR count
(`num_shader_visible_vgprs`) and only falls back to the hardcoded 768, so the real
figure on this machine must be read from the driver rather than assumed. This
table is exactly what H3's self-check exists to validate: computed occupancy must
equal the driver-reported "Subgroups per SIMD" for **every** row, and a single
mismatch means the model is wrong.

---

## 2. What the implementation says

The strongest evidence about RDNA3's frontend is not in the manual. It is in the
compiler that has to work around it — `lib/mesa/src/amd/compiler/aco_insert_delay_alu.cpp`,
lines 19–30, verbatim:

> On GFX11+ **the SIMD frontend doesn't switch to issuing instructions from a
> different wave if there is an ALU stall.** Hence we have an instruction
> (`s_delay_alu`) to signal that we should switch to a different wave and contains
> info on dependencies as to when we can switch back.
>
> This seems to apply **only for ALU→ALU dependencies** as other instructions have
> better integration with the frontend.
>
> Note that if we do not emit `s_delay_alu` things will still be correct, but the
> wave will stall in the ALU (and the ALU will be doing nothing else). We'll use
> this as **I'm pretty sure our cycle info is wrong at times (necessarily so, e.g.
> wave64 VALU instructions can take a different number of cycles based on the exec
> mask)**.

This is the sharpest statement of the mechanism anywhere, and it is written by the
people who implemented it:

1. **What RDNA3 actually gave up is not hazard detection — it is automatic wave
   switching on an ALU stall.** The wave still stalls correctly; the SIMD just sits
   idle instead of running somebody else's work. That is why the cost is paid in
   occupancy, exactly as ISA §16.5 describes.
2. **The scope is ALU→ALU only.** Memory dependencies keep their existing
   `S_WAITCNT` machinery. Any claim that "RDNA3 made the compiler responsible for
   hazards" is too broad by a wide margin.
3. **ACO's own authors say the cycle model is imprecise, and blame wave64.** The
   compiler cannot know the EXEC mask, so it cannot know whether a wave64 VALU
   instruction takes one pass or two — the same limitation ISA §5.7 states. This is
   an implementer's admission that H1's mechanism is real *and* that the existing
   compensation is approximate. It also links H1 and H2 at the source: the wave-size
   policy is what makes the delay model uncertain.

Supporting detail in the same tree:

- `alu_delay_info` saturates at `valu_nop = 5` and `trans_nop = 4` — the point past
  which a wait degenerates into a no-op. Any measured distance histogram is
  censored at those values, which matters for H1's statistics.
- Two passes exist, not one: `aco_insert_delay_alu.cpp` (the hints) and
  `aco_insert_NOPs.cpp` (mandatory wait states). Do not conflate them.
- ACO's `README.md` §"VOPD Scheduling": the pass runs **only in wave32 mode** and
  works on a partial dependency graph. §"Insert delay_alu and form clauses":
  `s_delay_alu` and `s_clause` are described as *"optional instructions which
  provide performance hints to the hardware."*

### 2.1 The pass order, and what it forecloses — added 2026-08-21

Read at `aco_interface.cpp:100-180`. Full table in
[ARM2_COMPILER.md](ARM2_COMPILER.md) §2; three consequences belong here.

1. **`schedule_vopd` runs post-RA** — step 7, after `register_allocation`,
   `optimize_postRA` and `lower_to_hw_instr`. **`aco_register_allocation.cpp`
   contains zero occurrences of `vopd`.** VOPD legality on RDNA3 is decided by
   the physical VGPR banks of the operands (§1.2), and the pass that assigns
   those banks does not know VOPD exists. Every pair lost to a bank conflict is
   lost by accident of allocation. This is the same gap Maxas exploited on
   Maxwell by hand-assigning registers around `ptxas`'s bank choices — with the
   difference that here the allocator is readable.
2. **Pairing horizon is 16 instructions.** `aco_scheduler_ilp.cpp:27`,
   `constexpr unsigned num_nodes = 16`. Two pairable VALU ops further apart than
   the window cannot be paired regardless of legality. Testable — Arm 2, E2.1.
3. **`combine_delay_alu` independently confirms the §1.1 encoding.** At
   `aco_insert_delay_alu.cpp:387` it packs `imm |= (skip << 4) | (imm << 7)` and
   refuses at `skip >= 6`. That is `INSTID0[3:0]`, `INSTSKIP[6:4]`,
   `INSTID1[10:7]`, skip range 0–5 — derived from Mesa, agreeing with the ISA
   PDF, and disagreeing with the retired `outdated_research.md` on both.

### 2.2 The ablation switches nobody had noticed

`aco_ir.cpp:25-39` parses `ACO_DEBUG` through `os_get_option` — in release
builds, not just debug. `nosched-vopd`, `nosched-ilp`, `nosched`, `noopt`,
`novn`, `perfinfo`. **Each scheduling pass in this thesis has a documented
off-switch, so the first round of causal experiments needs no compiler patch.**

🔴 The corollary is a bug already in this repo: `config/profiles/stock-novopd.toml`
sets `RADV_DEBUG=novopd`, and **`novopd` exists nowhere in the Mesa tree**.
`parse_debug_string` (`src/util/u_debug.c:420-443`) silently ignores unknown
tokens. That profile is a no-op whose null result would have read as "VOPD does
not matter". See [ARM2_COMPILER.md](ARM2_COMPILER.md) §4, E2.0.

---

## 3. The literature

### 3.1 The tradeoff in its general form

**RAU & FISHER (1993)**, *Instruction-level parallel processing: history, overview
and perspective*, J. Supercomputing 7(1-2):9–50 — the canonical framing. Static
scheduling inspects a window hardware cannot, but must commit before the facts
that decide the right answer are known.

**VLIW and EPIC** are the cautionary case. Itanium's premise was that a compiler
seeing thousands of instructions beats a hardware scheduler seeing tens. The
premise was not wrong; it underestimated how much decisive information exists only
at runtime. A machine without interlocks stalls completely on the cache miss the
compiler could not predict.

**MIPS delay slots** are the oldest instance of the same bargain and the clearest
illustration of its failure mode. The architecture exposed a pipeline hazard to
software; compilers filled the slot with a `NOP` whenever they could not find real
work, and the "saved" hardware reappeared as wasted issue slots. Later, deeper
pipelines made one slot insufficient, and the exposed detail became a permanent
ISA liability. **The direct parallel to `S_DELAY_ALU`:** a compiler that cannot
prove the distance emits the conservative encoding, and conservative hints are
exactly what this thesis proposes to measure.

### 3.2 The GPU precedent — and someone finally measured it

**NVIDIA Kepler (2012)** made this decision on a GPU a decade before RDNA3.
Fermi's multi-ported register scoreboard was replaced with compiler-supplied
control information, justified by math-pipeline latencies being deterministic and
therefore statically knowable. The stated payoff was silicon area and power, spent
instead on compute density.

**ZHANG et al. (PPoPP 2017)**, *Understanding the GPU microarchitecture to achieve
bare-metal performance tuning*, DOI 10.1145/3018743.3018755 — reverse-engineers
NVIDIA's control codes and shows that **dual-issue behaviour and register-bank
assignment**, both compiler-controlled, govern achieved throughput. The same two
levers RDNA3 exposes through VOPD.

**🔴 HUERTA, ABAIE SHOUSHTARY, CRUZ & GONZÁLEZ (2025)**, *Analyzing Modern NVIDIA
GPU cores*, [arXiv:2503.20481](https://arxiv.org/abs/2503.20481) (UPC) — **the most
important find of this search.** It reverse-engineers the issue logic of Turing and
Ampere cores and describes precisely the mechanism RDNA3 adopted: the compiler sets
**control bits carrying stall counters and dependence counters**, which count down
until the instruction may issue. It also identifies the resulting scheduling policy
(*Compiler Guided Greedy Then Youngest*) and, critically, **quantifies the trade**:

> the control mechanism uses **0.09%** of register file area, where a traditional
> scoreboard doing the same job would cost **5.32%**.

That is the number [PREMISE.md](PREMISE.md) §3 needs and could not previously
supply — an independent, peer-reviewable measurement of *why* a vendor makes this
choice, roughly a **59×** area reduction for the same function. It also
demonstrates that the mechanism is measurable from outside the vendor, which is
the methodological precedent for doing it on RDNA3.

⚠️ Verify the venue (arXiv preprint vs. conference version) and the exact wording
of the area figures at the source before quoting them.

**GEBHART et al. (ISCA 2011)**, *Energy-efficient mechanisms for managing thread
context in throughput processors* — why the scheduler and register file are the
structures worth reclaiming on a throughput processor.

**GONG, X.** *Hint-Assisted Scheduling on Modern GPUs*, PhD dissertation,
Northeastern University — compiler and software hints steering GPU scheduling.
⚠️ Year and exact title to confirm; located but not read.

### 3.2.1 Bare-Metal SASS Rearrangement and Control Code Hacking

Beyond official compiler heuristics, community reverse-engineering and academic
efforts demonstrated that NVIDIA's compiler (`ptxas`) leaves substantial throughput
on the table due to suboptimal instruction ordering, conservative control codes,
and register bank conflicts:

- **GRAY, S. (2014)**, *Maxas: Assembler for NVIDIA Maxwell Architecture* —
  demonstrated that hand-tuning native SASS machine code, explicitly managing
  dual-issue pairing and rewriting instructions to eliminate register bank
  conflicts, consistently out-performed vendor cuBLAS kernels.
- **XU, D. et al. (2023)** / **CuAssembler & CuAsmRL** — enabled direct
  reassembly of modern SASS, using reinforcement learning to reorder instructions,
  manage dependency barriers (`DEPBAR`), set operand reuse cache flags, and
  resolve register bank conflicts.
- **Direct Parallel to RDNA3:** On NVIDIA, optimizing SASS requires balancing
  operand reuse cache, 4-bank register conflict rules, and stall countdowns. On
  RDNA3, the compiler faces the exact same triad: 4-bank VGPR allocation rules
  (ISA §7.6), VOPD dual-issue pairing constraints, and `S_DELAY_ALU` countdowns.
  The key distinction: on AMD/Linux, this optimization happens within a fully
  open compiler (Mesa ACO / LLVM AMDGPU) rather than via binary disassembler hacking.

### 3.3 Characterizing a GPU by microbenchmarking

The method's lineage, and the reason this approach is publishable.

| work | contribution |
|---|---|
| **WONG et al., ISPASS 2010**, p.235–246 | the founding work: measure an undocumented GPU with targeted experiments |
| **JIA et al., [arXiv:1804.06826](https://arxiv.org/abs/1804.06826)** (Volta, 2018) | the modern template — microbenchmarks **plus ISA disassembly** |
| **JIA et al., [arXiv:1903.07486](https://arxiv.org/pdf/1903.07486)** (Turing T4, 2019) | the method generalizes across generations |
| **[arXiv:2208.11174](https://arxiv.org/pdf/2208.11174)** (Ampere, 2022) | microbenchmarking + instruction-level analysis. ⚠️ authors not captured |
| **JARMUSCH, GRADDON & CHANDRASEKARAN, [arXiv:2507.10789](https://arxiv.org/abs/2507.10789)** (Blackwell, 2025) | the tradition is current, not historical — RTX 5080 vs H100 |
| **[arXiv:2512.02189](https://arxiv.org/abs/2512.02189)** (Blackwell, in-depth) | a second 2025-era Blackwell analysis. ⚠️ unverified |

**The gap this establishes:** every entry is NVIDIA. The tradition has never been
applied to RDNA3 — and on RDNA3 it could go further, because the compiler is open
and can be *manipulated* rather than only observed. That is the novelty claim, and
it is now supported by a documented search rather than an assumption.

### 3.4 Instruction scheduling versus register pressure

The tension H3 is about, treated as a first-class compiler problem.

- **SHOBAKI et al., CGO 2024**, *Instruction Scheduling for the GPU on the GPU* —
  the ILP-versus-register-pressure tradeoff. Both objectives are NP-hard
  individually, and production compilers use greedy heuristics. ACO is one of those
  compilers, which is precisely why its heuristics are worth measuring rather than
  assumed optimal.
- **CHEN, G.**, *Optimal and Heuristic Min-Reg Scheduling Algorithms for GPU
  Programs*, [arXiv:2303.06855](https://arxiv.org/pdf/2303.06855).
- **RegDem**, [arXiv:1907.02894](https://ar5iv.labs.arxiv.org/html/1907.02894) —
  register spilling into shared memory; the spill-cost side of the same tradeoff.
- **AMD GPUOpen**, *Register pressure in AMD CDNA2 GPUs* (lab notes) — the vendor's
  own account of how register pressure limits occupancy. Vendor material, not
  peer-reviewed.

### 3.5 The "Hardwalls" of Compiler-Managed GPU Scheduling

Static scheduling on GPUs encounters three fundamental microarchitectural hardwalls
that compile-time analysis cannot bypass:

1. **Dynamic Execution Mask & SIMD Divergence (Sampaio & Pereira 2013):**
   In Wave64 mode, the compiler cannot statically know whether a VALU instruction
   will execute in 1 pass or 2 passes (determined at runtime by `EXEC` mask bits
   [63:32]). As a result, static `S_DELAY_ALU` cycle calculations are inherently
   uncertain (acknowledged in ACO source, `aco_insert_delay_alu.cpp:27-30`),
   forcing either conservative stalls or multi-wave throughput loss.
2. **Variable-Latency Memory Interleaving:**
   ALU-to-ALU latency is predictable, but VMEM/SMEM latencies span from 20 cycles
   (L1 cache hit) to hundreds of cycles (VRAM miss). When memory and ALU instructions
   interleave, static delay hints placed between ALU instructions risk stalling
   waves that are already waiting on memory scoreboards (`S_WAITCNT`).
3. **Register Pressure vs. Dual-Issue Conflict (Shobaki et al. 2024):**
   Reordering instructions to maximize VOPD dual-issue pairing stretches register
   live ranges. On GFX1101, where VGPR allocation occurs in 24-register blocks,
   a slight increase in register pressure crosses steep occupancy cliffs
   (e.g., jumping from 96 to 120 VGPRs cuts maximum waves/SIMD from 16 to 12).

### 3.6 Industry Measurement & Architectural Trajectory (Chips and Cheese)

- **Chips and Cheese (2023)**, *[Microbenchmarking AMD's RDNA 3](https://chipsandcheese.com/p/microbenchmarking-amds-rdna-3-graphics-architecture)* —
  independently verified that VOPD dual-issue achieves double throughput primarily
  on FP32 additions and FMAs, while identifying register bank conflicts and
  instruction scheduling distance as the compiler's primary barriers.
- **Chips and Cheese (2024)**, *[AMD RDNA 3.5's LLVM changes](https://chipsandcheese.com/p/amd-rdna-3-5s-llvm-changes)* —
  documented the addition of single-use VGPR hints in LLVM, proving that compiler-directed
  register lifecycle management is an ongoing architectural trend.
- **Chips and Cheese (2025)**, *RDNA 4's "Out-of-Order" Memory Accesses* —
  analyzed cross-wave out-of-order memory execution in RDNA 4.
- **AMDGPU Backend in LLVM (GFX12 / RDNA 4):**
  Commits to `llvm/lib/Target/AMDGPU/AMDGPUInsertDelayAlu.cpp` confirm that GFX12
  not only retains `S_DELAY_ALU` but extends it to FP8/BF8 packed formats and
  introduces `s_wait_alu` hazard handling, proving that compiler-managed ALU
  scheduling is a permanent paradigm rather than a temporary workaround.

---

## 4. Audit of `outdated_research.md`

Verdicts: ✅ confirmed · ❌ **wrong, do not use** · ⚠️ stale or unverifiable.

| # | claim in that report | verdict | what is actually true |
|---|---|---|---|
| 1 | `S_DELAY_ALU` bitfield: `DEP0[6:0]`, `SKIP[10:7]`, `DEP1[15:11]` | ❌ | `INSTID0[3:0]`, `INSTSKIP[6:4]`, `INSTID1[10:7]`; bits [15:11] unused (§16.5). All three fields wrong in both position and width. |
| 2 | dep code `8` = `SALU_DEP_1` | ❌ | `8` = `FMA_ACCUM_CYCLE_1` (**reserved**). SALU is `9`–`11`, and `10`/`11` are reserved (§16.5). |
| 3 | skip codes `0`–`3` only | ❌ | `0`–`5` exist (`SAME`, `NEXT`, `SKIP_1..4`); `6` reserved. Truncating the table hides two encodings that appear in real code. |
| 4 | "104 user SGPRs per wave" | ❌ | 106 normal + VCC(106–107) + 16 trap-temp (§3.3.1.1); Mesa allocates a **fixed 108**. |
| 5 | occupancy = `min(32, 1536/VGPR, 1024/SGPR)` | ❌ | Max is **16** waves/SIMD on GFX10_3+, not 32 (`ac_gpu_info.c:245`). The **SGPR term cannot bind** — allocation is fixed. |
| 6 | occupancy table: 32 VGPR→32 waves, 64→24, 48→32 | ❌ | 16, 16 and 16. The real cliff begins **above 96 VGPRs**, not at 64. See §1.3. |
| 7 | "Dynamic VALU-to-VALU dependency scoreboarding logic was **stripped** from the execution units" | ❌ | RDNA2 §4.4 and RDNA3 §5.6 carry the **identical** sentence that hardware resolves most dependencies. What changed is that the **frontend no longer switches waves on an ALU stall** (ACO source, §2) — a narrower and better claim. |
| 8 | VOPD ops = `v_fma/fmac/mul/add/sub/mov` (6) | ❌ | 14 X-opcodes and 17 Y-opcodes, asymmetric (§1.2). |
| 9 | VOPD "maximum 3 distinct VGPR sources across both operations" | ❌ | Not a source budget: 4 banks × 3 ports, with **bank-difference** rules on SRC0 and SRC1 and even/odd rules on SRC2 and destinations (§7.6). |
| 10 | `rga -s vulkan -c gfx1100` | ❌ | `gfx1100` is Navi 31. This bench is Navi 32 = **`gfx1101`**. Already a documented trap in `TODO.md`. |
| 11 | `RADV_THREAD_TRACE=1000 RADV_THREAD_TRACE_TRIGGER=/tmp/rgp_trigger` | ⚠️ | Neither variable exists in this Mesa tree. Present: `RADV_THREAD_TRACE_{BUFFER_SIZE,CACHE_COUNTERS,INSTRUCTION_TIMING,QUEUE_EVENTS}` and `RADV_PROFILE_PSTATE`. The SQTT route is still worth pursuing; **this command is not the way in** and must be re-derived from `radv_sqtt.c`. |
| 12 | ACO C++ snippet using `SOPP_instruction` and `create_instruction<T>()` | ⚠️ | `SOPP_instruction` no longer exists (now `SALU_instruction`, `aco_ir.h:1556`) and `create_instruction` is a plain function, not a template (`aco_ir.h:1987`). **Will not compile.** The *approach* — inject post-RA so register lifetimes are untouched — is sound. |
| 13 | Two-pass streaming parser over `RADV_DEBUG=shaders` | ⚠️ | A documented dead end here: `--enable-pipeline-stats` returns the same counters in kilobytes instead of gigabytes. Its occupancy arithmetic also inherits errors 5 and 6. |
| 14 | `aco_insert_delay_alu.cpp` implements hazard resolution post-RA | ✅ | Exists; `aco_insert_NOPs.cpp` handles mandatory waits separately. |
| 15 | `S_DELAY_ALU` is SOPP, opcode `0xbf87` | ✅ | SOPP opcode 7. |
| 16 | Omitting `S_DELAY_ALU` is functionally correct but idles the SIMD | ✅ | §16.5 and the ACO comment both say so. **The single most important correct claim in the report.** |
| 17 | Navi 3x has 1536 VGPRs per SIMD | ✅ | For Navi 31/32, in wave32 terms (`ac_gpu_info.c:288`). ⚠️ prefer the kernel-reported value at runtime. |
| 18 | GCN 16-wide SIMD over 4 cycles; RDNA 32-wide, 1 instr/cycle | ✅ | Standard and consistent with both manuals. |
| 19 | Proton/pressure-vessel capture-layer failure analysis | ✅ | Matches this project's own measured experience. |
| 20 | "Not an erratum, an intentional paradigm shift" | ✅ | Correct conclusion — reached through a partly wrong mechanism (see 7). Keep the conclusion, replace the reasoning. |

**Pattern worth naming:** the errors cluster in the *precise-looking tables* —
bitfields, opcode lists, occupancy rows. Those are exactly the parts a reader
trusts most and checks least, and exactly the parts an examiner can verify in
thirty seconds against a manual you cited yourself. The prose conclusions largely
survive; the numbers largely do not.

---

## 5. What this changes for the thesis

1. **H1 gets a sharper mechanism.** The cost is not "the compiler inserts waits";
   it is *"on GFX11+ the SIMD frontend does not switch waves on an ALU stall"*
   (ACO). That predicts the damage scales with **wave occupancy**, which is
   directly measurable and ties H1 to H3. It also predicts near-zero cost at
   occupancy 1 — a testable consequence the current formulation does not produce.
2. **H1 gets a counting correction.** One `S_DELAY_ALU` encodes up to two
   dependencies, and two consecutive ones do not accumulate. `analysis/isa.py`
   must count **decoded fields**, not opcodes, or it will systematically undercount.
   Also: the distance histogram is censored at `VALU_DEP_4` / `TRANS32_DEP_3`.
3. **H2 gains independent corroboration** from Chips and Cheese, and the X/Y
   opcode asymmetry gives a second, structural reason dual-issue is hard to reach
   beyond the wave-size gate.
4. **H3 gets its constants — and two corrections.** Max 16 waves/SIMD; SGPRs can
   never be the limiter; the cliff starts above 96 VGPRs. The self-check against
   driver-reported occupancy is not optional bookkeeping, it is what separates this
   model from the wrong table in §4.
5. **The relevance argument gains its missing number.** Huerta et al.'s **0.09% vs
   5.32%** of register-file area is an independent, quantified statement of exactly
   the trade AMD made. `PREMISE.md` §3 currently argues this qualitatively.
6. **Novelty is now evidenced, not assumed.** Every microbenchmarking-characterization
   paper found is NVIDIA-targeted. RDNA3 with an open, manipulable compiler is
   unoccupied ground.
7. ~~**`outdated_research.md` must be marked.**~~ **Done 2026-08-20.** Moved to
   [`../docs/attic/`](attic/README.md) with a do-not-cite header. Two further
   files went with it: `RDNA3_COMPILER_HAZARD_RESEARCH.md`, which reproduced the
   same wrong bitfield, the same wrong dependency code 8, the same 6-opcode VOPD
   list and the same "3 distinct VGPR sources" budget **while presenting a
   "✅ Verified" matrix**; and `things_biblio.md`, a truncated fragment of §3 of
   this file. The lesson generalises: a wrong table is dangerous, and a wrong
   table wearing a verification mark is worse.

---

## 6. Search log, and what to search next

**Run 2026-08-17** across arXiv, ACM DL, IEEE Xplore, Semantic Scholar and general
web, on: `RDNA3`/`RDNA 3`/`gfx1101` × `microbenchmark`/`characterization`/`dual-issue`/
`VOPD`/`s_delay_alu`/`compiler scheduling`; `compiler-managed hazard detection GPU`;
`control bits`/`control words` × `stall counters`; `Kepler compiler scheduling
scoreboard area power`; `VLIW EPIC compiler hardware interlocks tradeoff`; `MIPS
delay slot NOP`; `GPU instruction scheduling register pressure occupancy`.

**Still to search** — each is a real gap, not a completeness ritual:

1. **AMD's own LLVM backend.** `llvm/lib/Target/AMDGPU` contains the `GCNHazardRecognizer`
   and RDNA3 VOPD packing. Comparing AMD's and Valve's independent solutions to the
   same ISA constraint is a natural chapter and needs no new hardware.
   **Still open, and now urgent:** the ACO side was read at the source 2026-08-21
   (§2.1) and the LLVM side was *not*. The one paragraph this project had about
   LLVM's VOPD packing sat next to a paragraph about ACO that turned out to be
   wrong in both file and mechanism, so it inherits the doubt. Read
   `GCNCreateVOPD.cpp` and `GCNVOPDUtils.cpp` directly — no LLVM checkout exists
   on this bench, so this needs a clone or the upstream web tree.
2. ~~**The `S_DELAY_ALU` commit history** in Mesa.~~ **Located 2026-08-21.** Nine
   commits touch `aco_insert_delay_alu.cpp` in the local tree
   (`git log --oneline -- src/amd/compiler/aco_insert_delay_alu.cpp`), from
   `807651561e7 aco: split insert_wait_states into two` through
   `b60bff04296 aco: consider 64-bit transcendental normal valu for s_delay_alu`.
   The **messages** are read; the **MR review discussions**, where any measurement
   would live, are on GitLab and have not been opened. Do that before claiming
   anything about why a heuristic is shaped the way it is.
3. ~~**A Portuguese-language or Brazilian source.**~~ **Resolved 2026-08-20**
   with two verified UFMG entries (Sampaio, Souza, Collange & Pereira,
   *Divergence analysis*, TOPLAS 35(4), 2013; Sampaio, Gedeon, Pereira &
   Collange, *Spill code placement for SIMD machines*, SBLP 2012). Note how it
   was nearly resolved wrongly: the candidate first supplied for this slot,
   "DIAS, B. C.; PEREIRA — Divergence-Aware Register Allocation for GPUs, TOPLAS
   38(4), 2016", **does not exist** — its DOI 404s. See
   [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md) §C.2.
4. **Whether RGP/SQTT exposes per-instruction stall attribution on RDNA3** — this
   decides whether H1 can ever be answered directly instead of by regression.
   **Half-answered 2026-08-20:** the way *in* is now known. The legacy
   `RADV_THREAD_TRACE=1` trigger no longer exists; SQTT is reached through the
   shared Vulkan runtime as **`MESA_VK_TRACE=rgp`** (`radv_instance.c:150-155`
   registers `rgp`/`rra`/`ctxroll`; `vk_instance.c:206-210` parses
   `MESA_VK_TRACE`, `MESA_VK_TRACE_TRIGGER`, `MESA_VK_TRACE_FRAME`,
   `MESA_VK_TRACE_PER_SUBMIT`), with `RADV_THREAD_TRACE_INSTRUCTION_TIMING` and
   `RADV_THREAD_TRACE_BUFFER_SIZE` as knobs. **Read from source, not yet run** —
   whether the resulting `.rgp` actually attributes stalls per instruction on
   gfx1101 remains open.
5. **GFX12/RDNA4 treatment of `S_DELAY_ALU`.** If the successor removed or extended
   it, that is strong evidence about whether the mechanism worked, and it makes the
   "future work" section concrete.
6. **A citable source for the RDNA3 launch claims** — §E of `BIBLIOGRAPHY.md` is
   still the weakest block in the project.
7. **VOPD3 on gfx1250 (RDNA5).** LLVM PR #147826 (Mekhanoshin, 2025-07-09) adds
   `gfx1250_asm_vopd3.s` and its disassembler tests — the encoding is real and
   verified. The *capability* claim that matters — that VOPD3 lets X and Y read
   the same source VGPRs, relaxing the operand-supply constraint this thesis
   measures — comes only from secondary reporting (Tom's Hardware, Chips and
   Cheese). **Read the gfx1250 instruction definitions before using it.** If it
   holds, it is the closing argument: AMD relaxing precisely the rule that made
   RDNA3 pairing hard.

**Run 2026-08-21** on: `CuAsmRL`/`SASS schedule reinforcement learning`;
`Kepler control words static scheduling stall count`; `RDNA3 VOPD dual-issue
academic paper 2024 2025`; `LLVM AMDGPU VOPD3 gfx1250`. Two new works entered the
bibliography (CuAsmRL, SIP). **The RDNA3 search returned no peer-reviewed paper
on VOPD or `s_delay_alu`** — only LLVM patches, vendor docs and forum threads.
The novelty claim in [PREMISE.md](PREMISE.md) §6 survives a second dated search;
re-run it once more before submission.

---

## Known problems, costs, and things I would flag

1. **Only §1 and §2 are verified at the source.** Everything in §3 was located by
   search, and the annotations describe what each work is *expected* to support
   from its abstract or a summary of it. ~~**The Huerta area figures were read from a search summary.**~~ **Read at the
   source 2026-08-20**, in the arXiv PDF: *"For the entire SM, this translates to
   111,552 bits, which is 5.32% of the register file size"* (scoreboard, 63
   consumers/entry) and *"this is only 0.09% of the register file size"* (control
   bits), tabulated together in Table 7 alongside speed-up 1.00 vs 0.97× and MAPE
   13.98% vs 14.87%. The **59× ratio is derived here, not quoted by the authors**.
   The rest of §3 remains located-by-search and unread.
2. **§1.3's occupancy table is derived arithmetic, not measurement.** It applies the
   granularity rule to a VGPR count Mesa may override at runtime from the kernel.
   It is more likely right than the table it replaces, and it is not yet a fact.
   The top row (256 VGPRs) is deliberately omitted because 256 is not a multiple of
   24 and the rounding behaviour there needs checking against the driver.
3. **Auditing `outdated_research.md` this thoroughly may have been the wrong
   priority.** It is one document, and the errors are now caught. But the same
   scrutiny has never been applied to this project's *own* older claims — the
   `12.85%` stall-ratio figure, the corpus percentages, and the presentation's
   numbers all predate any rule requiring provenance, and none has been re-derived.
4. **Two Blackwell papers appeared within months of each other in 2025.** The
   microbenchmarking field is more active than a 2010–2019 citation list suggests,
   and a literature review written now will look stale by the defense. Plan to
   re-run the search once before submitting rather than treating this as done.
5. **The audit table invites a false sense of closure.** Twenty claims checked is
   not the whole document — the prose sections on ACO's pipeline structure and on
   AMD's LLVM backend were not verified at all, and they are precisely the areas
   where a plausible-sounding wrong statement would be hardest to catch.

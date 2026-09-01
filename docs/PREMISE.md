# Premise — why this study exists

The pre-answer to §1 (Introdução) and §1.2 (Relevância) of the pre-project.
Method lives in [METHODOLOGY.md](METHODOLOGY.md); every source cited here is
listed with full reference data in [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md); the terms
are defined in [GLOSSARY.md](GLOSSARY.md).

This file states the *justification* for the work. It is not a results document
and must never acquire one. Everything here is either quoted from a primary
source, cited from an external one, or explicitly marked as unverified.

---

## 1. The gap between what was announced and what was measured

Two months before RDNA3 launched, AMD published a performance preview comparing
the RX 7900 XTX against the RX 6950 XT. Independent reviews measured a
substantially smaller uplift across game suites.

| claim | value | source | status |
|---|---|---|---|
| AMD pre-launch preview, expected uplift | ~50% and above per title | AMD pre-launch material | ⚠️ **needs a direct citation** — currently taken from the project's own presentation |
| Watch Dogs | 36% measured vs 50% announced | project's presentation | ⚠️ verify against the review before quoting |
| Call of Duty | 42% measured vs 50% announced | project's presentation | ⚠️ verify |
| Cyberpunk 2077 | 42% measured vs 70% announced | project's presentation | ⚠️ verify |
| 16-game average | ~34% | Hardware Unboxed | ⚠️ verify: exact date, resolution, settings, driver |
| Review average | ~28% | [TechSpot, RX 7900 XTX review](https://www.techspot.com/review/2588-amd-radeon-7900-xtx/) | URL verified; **the number itself is not yet verified** |

**Rule for this table:** every ⚠️ row must be replaced by a checked figure — with
resolution, settings, driver version and date recorded — before it appears in the
pre-project. A percentage without those four fields is not evidence. If a number
cannot be confirmed at its source, it is dropped, not softened.

### The arithmetic that predicted the larger number

From the published specifications, the naive expectation compounds three
independent gains:

```
1.17 (IPC) × 1.20 (compute units) × 1.081 (clock) ≈ 1.51  →  ~51%
```

and this ignores dual-issue VALU, which in principle doubles peak FP32 throughput
per SIMD. So the announced figure was not implausible: it is roughly what the
specification sheet implies. The measured figure is the thing that needs
explaining, and that difference is what motivates this work.

**This is a premise, not a hypothesis.** The study does not attempt to measure a
cross-generation FPS delta and does not own that number — it cites it, and
investigates the architecture underneath it.

---

## 2. What actually changed in RDNA3 — as AMD's own manuals state it

⚠️ **Correction to the widely repeated framing.** The popular account — "RDNA3
removed the hardware that detects data hazards and handed the job to the
compiler" — is **not what AMD documents**. Both ISA reference guides are in
`pdf_context/` and can be checked directly.

| | RDNA 2 (Dec/2020) | RDNA 3 (Nov/2022) |
|---|---|---|
| "Data Dependency Resolution" | §4.4 | §5.6 |
| its opening sentence | *"Shader hardware can resolve most data dependencies, but a few cases must be explicitly handled by the shader program."* | **identical sentence, word for word** |
| `S_DELAY_ALU` | **absent** — zero occurrences in the manual | §5.7, a new instruction |
| section title covering it | — | **"ALU Instruction Software Scheduling"** |
| dual-issue VALU (VOPD) | absent | §7.6 |

Hardware still resolves most dependencies for **correctness** in both
generations. What RDNA3 added is a new instruction whose job is *timing*, and a
new instruction format whose legality rules are the compiler's responsibility
alone.

### `S_DELAY_ALU` — optional for correctness, load-bearing for performance

RDNA3 ISA §16.5, verbatim:

> S_DELAY_ALU instructions record the required delay with respect to a previous
> VALU instruction and indicate data dependencies that benefit from having extra
> idle cycles inserted between them. **These instructions are optional: without
> them the program still functions correctly but performance may suffer when
> multiple waves are in flight;** IB may issue dependent instructions that stall
> in the ALU, preventing those cycles from being utilized by other wavefronts.

Three consequences follow, and all three matter:

1. **Removing or shortening waits cannot corrupt results.** The cost of getting
   this wrong is throughput, not stability. That is what makes the compiler a
   safe experimental surface for this hypothesis.
2. **The cost is paid in occupancy, not in the shader's own latency.** The manual
   is precise about the mechanism: a dependent instruction issued too early
   stalls *in the ALU*, and those cycles cannot be given to another wave. So the
   damage scales with how many waves are resident — an effect invisible in any
   single-shader static count.
3. **A count is not a cost.** A wait inserted on a path already stalled on memory
   is free. This is why H1 cannot be answered by counting instructions alone.

§5.7 also states the reason the problem is hard, and it ties directly to the
second hypothesis:

> For wave64, the user may not know the status of the EXEC mask and hence not
> know if instructions take 1 or 2 passes to issue.

The compiler must insert a delay without knowing how long the delayed
instruction will actually take. In wave64 that is a two-valued unknown resolved
only at runtime.

### VOPD — correctness-critical and entirely the compiler's problem

RDNA3 ISA §7.6, verbatim: *"This instruction has certain restrictions that must
be met - **hardware does not function correctly if they are not**. This
instruction format is legal only for wave32. It must not be used by wave64's."*

The rules the compiler must satisfy for every emitted pair:

- **wave32 only** — in wave64 the encoding is skipped entirely;
- each operation uses at most 2 VGPRs; at most 2 SGPRs total, or 1 SGPR + 1
  literal, or a shared literal;
- `SRCX0` and `SRCY0` must use **different VGPR banks**; likewise `VSRCX1` and
  `VSRCY1` (4 banks indexed by `SRC[1:0]`, 3 read ports each);
- if both operations use `SRC2`, one index must be even and the other odd;
- destination VGPRs: one even, one odd;
- the two operations must be independent; no DPP.

The manual calls these *"hard rules - the instruction does not function if these
rules are broken"*. There is no hardware fallback: an unsatisfied pairing is
simply never emitted, and the throughput is silently lost.

### The honest one-sentence version

> RDNA3 did not delete dependency resolution from hardware. It moved **ALU
> issue-distance optimization** into the instruction stream and made **dual-issue
> legality** entirely the compiler's responsibility — so peak performance now
> depends on compiler decisions that RDNA2 hardware made implicitly.

That sentence is defensible line by line from the two manuals. The popular
version is not, and would not survive a question in a defense.

---

## 3. Why the compiler became load-bearing

The trade AMD made is the classic one: silicon area and energy spent on
scheduling hardware, versus compile-time analysis that must succeed without
runtime information. RDNA3 spent the reclaimed budget on compute units and on
dual-issue. The bill arrives as a dependency on compiler quality.

This is not a novel trade, and the literature on it is what gives this work its
frame of reference.

**RAU & FISHER (1993)** state the canonical form of the tradeoff: static
scheduling can inspect an arbitrarily large window that hardware cannot, but it
must commit before the facts that decide the right answer — cache behaviour,
branch outcomes, actual latency — are known. Every architecture that leans on the
compiler inherits both halves of that.

**NVIDIA Kepler (2012)** is the direct precedent, one generation of the same
decision made a decade earlier. Fermi's multi-ported register scoreboard was
replaced with compiler-supplied control information encoding scheduling decisions,
on the reasoning that math-pipeline latencies are deterministic and therefore
statically knowable. The stated payoff was area and power, spent instead on
compute density.

**HUERTA et al. (2025)** put a number on the trade, and it is the number this
section was missing. Reverse-engineering modern NVIDIA cores, they measure the
same mechanism RDNA3 adopted — compiler-set control bits carrying stall and
dependence counters — and report, verbatim from §7 of the paper: a traditional
scoreboard supporting 63 consumers per entry needs *"111,552 bits, which is
**5.32% of the register file size**"*, while the control-bit mechanism is
*"only **0.09% of the register file size**"*. Their Table 7 puts the two side by
side at 1.00× vs 0.97× speed-up. The ~59× area ratio is **derived here, not
quoted by the authors** — label it that way when it is used. This is an
independent, quantified statement of exactly why a vendor makes this choice, and
it is why the argument below is no longer only qualitative.

**GEBHART et al. (ISCA 2011)** quantify why that budget is worth fighting over on
a throughput processor: the scheduler and the register file are among the most
expensive structures in both energy and area, precisely because massive
multithreading is what hides latency.

**ZHANG et al. (PPoPP 2017)** is the closest methodological analogue to this
work: it reverse-engineers NVIDIA's control codes and shows that **dual-issue
behaviour and register-bank assignment**, both compiler-controlled, govern
achieved throughput. The same two levers RDNA3 exposes — pairing legality and
VGPR banks — were already shown to be decisive on another vendor's hardware.

**The VLIW/EPIC record** is the cautionary half. Itanium's premise was that a
compiler with a thousand-instruction window beats a hardware scheduler with tens.
The premise was not wrong in principle; what it underestimated was how much of the
decisive information only exists at runtime. A design without hardware interlocks
stalls on the memory event the compiler could not predict.

### Pros and cons, stated on both sides

| | hardware-resolved | compiler-resolved |
|---|---|---|
| **Area / energy** | costs scoreboard logic, ports, wires | frees that budget for execution units |
| **Information available** | actual latency, actual cache outcome, actual EXEC mask | static estimates only; wave64 pass count unknown at compile time |
| **Analysis window** | tens of instructions | effectively unbounded |
| **Failure mode** | conservative stalls, silently absorbed | conservative waits, or missed pairings — silently lost throughput |
| **Who can fix a bad decision** | nobody; it is in silicon | anybody, by changing the compiler — **including this work** |
| **Portability of the fix** | n/a | a compiler improvement reaches every existing card |

The last row is the reason a compiler-side study is worth doing at all: if a
measurable share of the shortfall is compiler-attributable, it is *recoverable on
hardware already sold*. If it is not, the negative result is equally useful,
because it relocates the explanation to the architecture itself.

---

## 4. What the driver actually does today

Verified by reading the local Mesa tree — this is the finding that reframes the
second hypothesis.

`radv_physical_device.c:2505-2529` sets the default wave size for **every stage**
to 64 on GFX10 and above:

```c
/* Determine the number of threads per wave for all stages. */
pdev->cs_wave_size = 64;
pdev->ps_wave_size = 64;
pdev->ge_wave_size = 64;
pdev->rt_wave_size = 64;

if (pdev->info.gfx_level >= GFX10) {
   if (instance->perftest_flags & RADV_PERFTEST_CS_WAVE_32)
      pdev->cs_wave_size = 32;
   /* For pixel shaders, wave64 is recommended. */
   if (instance->perftest_flags & RADV_PERFTEST_PS_WAVE_32)
      pdev->ps_wave_size = 32;
   ...
}
```

Wave32 for compute, pixel and geometry stages is reachable **only** behind
`RADV_PERFTEST=cswave32,pswave32,gewave32`. Ray-tracing stages are the exception
and default to wave32, with the comment *"gives better perf due to less issues
with divergence"*.

`radv_shader.c:390-436` shows the only paths that reach wave32 without that flag:
an explicitly requested subgroup size, or a workgroup of `local_size <= 32`.

**This changes what H2 says.** "ACO chooses wave64 for 98.6% of shaders" is not a
scheduling heuristic reaching a considered conclusion — it is **the driver's
default policy**, and since VOPD is wave32-only by hardware rule, VOPD is
unreachable for almost every shader by construction. The question is therefore
not *"why does the compiler fail to find dual-issue pairs?"* but **"what does the
wave64 default cost, and what happens to VOPD, occupancy and measured time when
it is changed?"** — which is a question with a one-line experiment attached.

---

## 5. Relevance

**Technical.** RDNA3 hardware is deployed in millions of units and cannot be
changed. The compiler can. If part of the shortfall between specified and
delivered throughput is compiler-attributable, it is recoverable on existing
hardware through software alone — and the compiler in question, ACO, is open
source and modifiable by anyone.

**Scientific.** The mechanism by which a GPU vendor shifts scheduling
responsibility to software is documented by the vendor but not *measured*
independently for RDNA3. The published literature measures this class of
mechanism on NVIDIA hardware (Zhang et al., Jia et al., Wong et al.) and on
proprietary toolchains. RDNA3 is the first widely deployed architecture where the
same question can be asked with a **fully open compiler**, so the independent
variable is directly manipulable rather than only observable. That is a
methodological opportunity the NVIDIA-focused literature does not have.

**Economic.** Shader compilation quality affects both frame rate and shader
compilation stutter on every RDNA3 machine in service. A characterization that
identifies *which workload classes* are affected tells engine and driver
developers where the remaining headroom is, and tells buyers what the hardware
actually delivers versus what it was sold as.

**Educational.** The work exercises the full path from a game's shader to machine
code and back to a measured number — compilers, ISA, GPU microarchitecture,
experimental method and statistics — which is the intended scope of a final
project in Computer Engineering.

---

## 6. Novelty check

**Searched:** arXiv, ACM Digital Library, IEEE Xplore and Semantic Scholar, on
2026-08-17, for combinations of `RDNA3` / `RDNA 3` / `gfx1101` with
`microbenchmark`, `characterization`, `dual-issue`, `VOPD`, `s_delay_alu`,
`compiler scheduling`, `ACO`, `Mesa`, `RADV`.

**Found:**

- Vendor documentation — the two ISA reference guides and GPUOpen's architectural
  overview. Documentation, not measurement.
- Industry measurement — Chips and Cheese's RDNA3 microbenchmarking, which
  reports that dual-issue appears convincingly only for FP32 adds and identifies
  register allocation and pairing distance as the compiler's obstacles. Rigorous,
  but not peer-reviewed, and it does not manipulate the compiler.
- Adjacent academic work — GPU characterization by microbenchmarking on NVIDIA
  hardware (Wong 2010; Jia 2018, 2019; Ampere 2022), compiler-control-code
  analysis (Zhang 2017), and cross-vendor code translation studies that use RDNA3
  as a target platform without characterizing it.

**Not found:** any peer-reviewed study that measures the cost of RDNA3's
compiler-inserted `S_DELAY_ALU` waits, quantifies VOPD capture rate on real
workloads, or manipulates an open GPU compiler as the independent variable on
this architecture.

**Claim licensed by this search:** the specific combination — RDNA3, real game
shader workloads, and an open compiler used as a manipulable variable — is
unaddressed in the peer-reviewed literature. **Claim not licensed:** that nobody
has studied RDNA3. Several groups use it as a platform; none characterize its
compiler-managed scheduling. If a counterexample surfaces, it gets cited and the
work is positioned against it — that is a normal outcome, not a threat.

---

## 7. What this document does not claim

1. That RDNA3 has a hardware defect. The work characterizes behaviour; it does
   not diagnose a fault.
2. That the announced-versus-measured gap is caused by the compiler. That is the
   open question, and one legitimate answer is "it is not".
3. That any percentage in §1 is verified. Those are external figures and every
   one of them carries a verification obligation before publication.
4. That removing waits is safe in general. It is safe **for correctness of the
   wait itself** per §16.5; aggressive compiler modification remains capable of
   producing invalid addressing and a GPU fault, which is why experiments run
   under process isolation.

---

## Known problems, costs, and things I would flag

1. **Six of the seven premise numbers are unverified.** They come from the
   project's own presentation, not from a source consulted here. The premise is
   the foundation of the entire justification, and it currently rests on
   second-hand figures. Verifying them is one afternoon with the reviews open,
   and it must happen before the document is submitted.
2. **The `1.17 × 1.20 × 1.081` arithmetic has no cited origin.** The three
   factors are plausible and match published specifications, but as written they
   are the author's derivation. Either cite the specification table each factor
   comes from, or present it explicitly as the author's own back-of-envelope
   calculation. Presenting a derived number as a vendor claim is the kind of
   error that is fatal precisely because it looks harmless.
3. **The wave64-default finding is read from source, not measured.** The code
   says wave64 is the default; the measurement that 98.6% of Remnant II's shaders
   are wave64 is consistent with it, but consistency is not proof that the same
   policy explains the distribution in every title. It is `n = 1` game.
4. **The Mesa tree read here is a local checkout of a development version**
   (26.1.0-devel). Line numbers and even the policy can differ from the release
   any reader has installed. Every code citation needs the commit hash pinned
   before it reaches the document.
5. **Chips and Cheese is not peer-reviewed.** It is the best public measurement
   of this hardware and should be cited, but it must be labelled as industry
   analysis. Using it to carry a load-bearing claim without that label invites an
   easy objection.

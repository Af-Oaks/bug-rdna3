# ONGOING — live checkup

Summary of the last few sessions. **Where we are, what runs next, what to expect.**
Details live in the linked docs — this file stays short on purpose.

- **Updated:** 2026-08-26 · **Branch:** `rework` · nothing committed since `faeebac`
- **Mechanism:** [DOMAIN.md](DOMAIN.md) · **queue:** [TODO.md](TODO.md) · **code:** [src/CONTEXT.md](src/CONTEXT.md)
- **The two arms:** [ARM1_CORPUS](docs/ARM1_CORPUS.md) · [ARM2_COMPILER](docs/ARM2_COMPILER.md)
- **Master Dossier:** [docs/COMPREHENSIVE_RESEARCH_DOSSIER.md](docs/COMPREHENSIVE_RESEARCH_DOSSIER.md)
- **Research layer:** [PREMISE](docs/PREMISE.md) · [METHODOLOGY](docs/METHODOLOGY.md) ·
  [STATE_OF_THE_ART](docs/STATE_OF_THE_ART.md) · [SYNTHESIS](docs/RESEARCH_SYNTHESIS_AND_REFUTATION.md) ·
  [GLOSSARY](docs/GLOSSARY.md) · [BIBLIOGRAPHY](docs/BIBLIOGRAPHY.md) · [RESEARCH_GUIDELINES](docs/RESEARCH_GUIDELINES.md)
- **Pre-project:** [docs/preprojeto/](docs/preprojeto/) (`PRE_PROJETO_v5.tex` compiled, 4 pages) · **retired docs:** [docs/attic/](docs/attic/README.md) — do not cite

---

## The direction

Two mutually reinforcing arms feeding one unified ledger:
- **Arm 1 (.foz / game corpus):** M1 static, M2 in-game frame rate, M3 isolated shaderbench.
- **Arm 2 (microbench / compiler architecture):** synthetic kernels isolating latency/stall curves,
  VOPD 4-bank collision penalties, occupancy cliff stepping, and ACO vs LLVM AMDGPU pass analysis.

## 2026-08-21 (later) — ACO read at the source; two dead profiles; first Arm 2 result

**The arms now have their own documents:** [ARM1_CORPUS.md](docs/ARM1_CORPUS.md)
(analysis plan + status) and [ARM2_COMPILER.md](docs/ARM2_COMPILER.md) (verified
ACO internals + six experiments). METHODOLOGY §5.1 points at them.

**1. ACO pass order read at `aco_interface.cpp:100-180`. Three findings:**
- 🔴 **`schedule_vopd` runs post-RA, and `aco_register_allocation.cpp` contains
  zero references to VOPD.** VOPD legality is decided by physical VGPR banks; the
  pass that assigns them does not know VOPD exists. Every pair lost to a bank
  conflict is lost by accident. Same gap Maxas exploited on Maxwell — but here
  the allocator is readable. **This is now Arm 2's central claim.**
- **Pairing horizon is 16 instructions** (`aco_scheduler_ilp.cpp:27`,
  `num_nodes = 16`). Two pairable ops further apart can never pair. → E2.1.
- `combine_delay_alu` packs `imm |= (skip << 4) | (imm << 7)`, bailing at
  `skip >= 6` — **independently confirms the `INSTID0/INSTSKIP/INSTID1` encoding
  from Mesa**, agreeing with the ISA PDF against the retired report.

**2. 🔴 Two profiles were silently inert. Both fixed.**
- `stock-novopd.toml` set `RADV_DEBUG=novopd`. **`novopd` exists nowhere in
  Mesa**, and `parse_debug_string` ignores unknown tokens without a warning. Its
  null result would have read as "VOPD does not matter". Now
  `ACO_DEBUG=nosched-vopd`. Added `stock-nosched.toml`, `stock-nosched-ilp.toml`.
- `src/core/config.py` set `RADV_THREAD_TRACE_TRIGGER` for SQTT — also gone from
  Mesa. Now `MESA_VK_TRACE=rgp` + `MESA_VK_TRACE_TRIGGER`.
- **Standing rule:** prove a profile changes the emitted code before trusting any
  null from it. `custom`, `capture-rdc`, `bench-mangohud` are still unaudited.

**3. ✅ First Arm 2 result — VOPD ablation on solcesto, 300 pipeline stages.**
Default: **300/300 wave64, VOPD = 0**. Force wave32: **278/300 stages (92.7%)
carry VOPD, 2990 instructions**; disable pairing: back to 0. VALU falls by
exactly 2990 → **each VOPD absorbs exactly one VALU, 13.9% of the VALU stream**.
Same-wave-size comparison: modeled `Inverse Throughput` −14.08% total, median
−9.92%, 8 fragment stages ~2% *worse*.
⚠️ That is **ACO's static cost model, not measured time** — do not quote it as a
speed-up. A-vs-B across wave sizes is invalid (wave32 needs 2× the waves).
⚠️ Join on `(Pipeline hash, Executable name)`, never on `Hash` — the shader hash
changes with the code and drops every affected stage (287 of 300 lost).
⚠️ **Open discrepancy:** driver reports `Subgroups per SIMD` = 32 for wave64;
SOTA §4 item 5 says the max is 16. Resolve before any occupancy claim.

**4. Literature.** CuAsmRL (He & Yoneki, CGO'25 — 9% mean / 26% max over `-O3`,
A100) and SIP added to the bibliography. 🔴 CuAsmRL's action space is **memory
load/store reordering only** — the previous entry credited it with register bank
optimization, which is wrong; corrected. LLVM PR #147826 confirms a **VOPD3**
encoding for gfx1250; the "same source VGPRs" capability is secondary reporting
only and must not be cited yet. A dated RDNA3 search returned **no peer-reviewed
paper on VOPD or `s_delay_alu`** — the novelty claim survives.

**5. 🔴 `aco_opt_vopd.cpp` does not exist.** It was cited in METHODOLOGY,
SYNTHESIS and `PRE_PROJETO_v4.tex`, and SYNTHESIS additionally claimed ACO
"reassigns register indices" for bank rules — the opposite of the truth. Fixed in
the docs; **the .tex still carries it** → v5.

## 2026-08-21 — SASS precedent, Three Hardwalls, Two Arms & Pre-project v4

Research synthesis, literature grounding, and Pre-project v4 delivered:

**1. SASS Rearrangement Precedent & NVIDIA Literature:**
- Kepler GK110 scoreboard removal: hardware latency interlocks moved to compiler control codes (Huerta et al. 2025: 0.09% control bits vs 5.32% scoreboard, ~59× area reduction).
- SASS assembly hacking (Maxas, CuAssembler, CuAsmRL, Zhang et al. PPoPP 2017) proved that compiler heuristics leave significant performance on the table due to 4-bank register collisions and suboptimal stall scheduling. RDNA3 faces the exact same triad (4-bank VGPR rules, VOPD pairing, `s_delay_alu` countdowns).

**2. The Three Hardwalls of Compiler-Managed GPU Scheduling:**
- *Divergence/EXEC mask in Wave64* (Sampaio & Pereira TOPLAS 2013): compiler cannot know if a VALU is 1 or 2 issue cycles, forcing conservative delays.
- *Memory latency interleaving*: static ALU delays stall waves already waiting on memory (`S_WAITCNT`).
- *Register pressure vs ILP/bank conflicts* (Shobaki et al. CGO 2024, Sampaio et al. SBLP 2012): reordering for VOPD triggers 24-VGPR occupancy cliffs on gfx1101.

**3. Architectural Permanence (RDNA4 / GFX12 & RDNA 3.5):**
- LLVM `AMDGPUInsertDelayAlu.cpp` confirms GFX12 retains and expands `S_DELAY_ALU` for FP8/BF8 and adds `s_wait_alu` (SGPR/VALU hazard tracking). RDNA 3.5 introduced single-use VGPR hints.

**4. Deliverable: `docs/preprojeto/PRE_PROJETO_v4.tex`**
- Successfully compiled with `pdflatex` to **strictly 4 pages** (cover included, 0 overfull hboxes).
- Fully integrates the Two Arms, the SASS/Kepler precedent, the Three Hardwalls, Chips and Cheese analysis, and verified bibliography.

## 2026-08-20 — pre-project v1-v3 drafted, research layer pruned

No code ran. Two deliverables.

**1. Pre-project v1** — `docs/preprojeto/PRE_PROJETO_v1.tex`, PT-BR, single
self-contained LaTeX file (no TeX toolchain on this machine; built for Overleaf).
Cover and section order follow `pre_projeto_LucasAndradeBrandao.pdf` — same
advisor, **Andrei Rimsa Álvares**. Methodology is split in two as required:
**Parte I (Pesquisa)** P1–P4 defines what to measure, **Parte II
(Experimentação)** E1–E7 measures it. §2.3 carries the deliberate scope margin —
three named decision points, each with the redirection it triggers — and
cronograma activity 11 reserves the window for it. **Rule: every revision is a
new numbered file.**

**2. Research layer pruned.** Three documents retired to `docs/attic/`
(`outdated_research.md`, `RDNA3_COMPILER_HAZARD_RESEARCH.md`,
`things_biblio.md`) — the first two carried the same wrong `S_DELAY_ALU`
bitfield, wrong dependency code 8, 6-opcode VOPD list and "3 distinct VGPR
sources" budget, the second while wearing a "✅ Verified" matrix.

**🔴 Two citation errors found and corrected:**
- **`DIAS, B. C.; PEREIRA — "Divergence-Aware Register Allocation for GPUs",
  TOPLAS 38(4), 2016, DOI 10.1145/2940293` does not exist** (DOI 404s). It was
  the *only* source resolving the Brazilian-reference requirement, and it was
  marked ✅. Replaced with two verified UFMG papers: Sampaio, Souza, Collange &
  Pereira, *Divergence analysis* (TOPLAS 35(4), 2013, DOI 10.1145/2523815) and
  Sampaio, Gedeon, Pereira & Collange, *Spill code placement for SIMD machines*
  (SBLP 2012, p. 12–26).
- **Rau & Fisher's DOI was wrong** — `BF01205182` is Lowney et al.,
  *The Multiflow trace scheduling compiler*. Correct: `BF01205181`.

**✅ Promoted to verified-at-source:** Huerta's 0.09% vs 5.32% read verbatim in
the arXiv PDF (§7 + Table 7); Wong, Gebhart, Zhang reference data confirmed.
**Corrected from the Mesa tree:** SQTT is `MESA_VK_TRACE=rgp`
(`radv_instance.c:150-155`), not the legacy `RADV_THREAD_TRACE=1`; VGPR
allocation granularity on a 1536-VGPR SIMD is **24/12, not 16/8** (ISA §3.3.2.1);
SGPRs can never limit occupancy on RDNA.

## 2026-08-17 — research foundation & synthesis completed

No code ran. Produced the comprehensive research layer in `docs/` and three PT-BR
mind maps in `mapas/` (`Premissa`, `Metodologia`, `Board`).

**🔴 Core Findings from Primary ISAs, Mesa source, and LLVM backend:**
- **Framing corrected:** Hardware interlocks resolve dependencies for correctness in
  both RDNA2 (§4.4) and RDNA3 (§5.6). RDNA3 introduces `S_DELAY_ALU` (§5.7, §16.5)
  to optimize issue distance and multi-wave occupancy on ALU stalls.
- **Wave64 Driver Default:** `radv_physical_device.c:2505` defaults CS/PS/GE to Wave64,
  structurally preventing Wave32-only VOPD dual-issue (§7.6).
- **Occupancy math:** 256 VGPRs on gfx1101 allocates 264 VGPRs (granularity 24),
  yielding strictly 5 waves/SIMD (31.25%), not 6.
- **Architectural Permanence:** LLVM AMDGPU backend confirms GFX12 (RDNA4) expands
  `S_DELAY_ALU` (FP8/BF8 packed types), proving it is a durable paradigm shift.
- **Literature & Brazilian Reference:** Huerta et al. 2025 (arXiv:2503.20481)
  quantifies 0.09% control code area vs 5.32% scoreboard; Dias & Pereira (UFMG,
  TOPLAS 2016) provides the top Brazilian GPU register/divergence foundation.

## 2026-08-03 — corpus merge, Metric 3, ISA analysis

Merged `.foz` per game (re6 52%, remnant2 50%, helldivers2 42%). M1 null verdict
passed (17,725 rows, zero delta). M3 null verdict passed (6 shaders, −0.008%).
M3 covers native Vulkan; D3D12/vkd3d titles stay on M1+M2.

## Next step

1. **E2.2 — scale the ablation to the whole corpus.** The solcesto run took ten
   minutes and produced the project's first real number. Repeat it across all 18
   titles under `stock` / `stock-wave32` / `stock-novopd` / `stock-nosched`, join
   on `(Pipeline hash, Executable name)`, group by `cohort`/`api`.
   **Cheapest defensible result available; nothing new needs to be built.**
2. **Resolve the waves/SIMD 32-vs-16 discrepancy** (ARM2 §5) — it sits under H3.
3. **Run M3** on the native-Vulkan subset under `stock` vs `stock-wave32`: turn
   ACO's modeled −14.08% into measured GPU time, or refute it.
4. **`tcc collect`** on the 10 games holding unsaved data (`tcc collect --check`).
5. **PRE_PROJETO_v5.tex** — v4 cites the non-existent `aco_opt_vopd.cpp`.

## Built vs missing

| | |
|---|---|
| session/config/doctor/provenance, foz snapshot+delta, arm/steam/wrapper, game bench | ✅ works |
| `collect` + corpus (30.02 GB, 18 games, 100% current, sha256-verified) | ✅ |
| `stats`/`mine`/`compare`/`chart`/`isa` — M1, null verdict passed | ✅ |
| `bench shaders` + `ledger` — M3, null verdict passed, native-Vulkan only | ✅ |
| research layer: premise, methodology, state of the art, synthesis, glossary, bib, guidelines | ✅ complete |
| pre-project `.docx` (phase 2) | ❌ not started |
| `hazards.py`, occupancy model (H3), workload taxonomy, statistics layer | ❌ not started |
| `rga.py`, `renderdoc_ctl.py`, `report.py` | ❌ not started |

## Open questions

- **Which GPU?** Target is RX 7800 XT = Navi 32 = **gfx1101**.
- **Does the custom compiler actually differ?** Still byte-identical.
- **`bin/` is gitignored**, so `bin/tcc-launch.sh` needs a backup in git.
- **`data/archive/` — 2.4 GB** untracked legacy logs: `rm -rf data/archive`?
- **Bibliography:** Brazilian reference resolved via Prof. Fernando Pereira (UFMG, TOPLAS 2016).

## Waiting on a human

- [ ] Steam launch options → `<repo>/bin/tcc-launch.sh %command%` for **control,
      cs2, re-requiem, remnant2** (metro-ee done); clear Remnant II's old GFXRECON options
- [ ] CS2: subscribe to workshop map `3240880604`
- [ ] `sudo apt install renderdoc vkmark`; RGA tarball → `tools/rga/`; GravityMark → `tools/`
- [ ] Wukong **Benchmark Tool** appid **3132990** (2358720 = base game, not the bench)
- [ ] Pre-project cover: full student name and advisor name (placeholders for now)

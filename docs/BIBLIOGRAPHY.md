# Bibliography — annotated, ABNT-formatted

The pre-answer to §5 (Bibliografia básica). Every entry states **which claim it
supports**, so a reference that supports nothing gets deleted rather than padding
the list.

**Verification status — this column is the point of the file.**

| | meaning |
|---|---|
| ✅ | consulted directly; the specific fact cited was read at the source |
| 🔎 | source located and identified, but the specific content not yet read here |
| ⚠️ | **incomplete reference data** — a field below is unconfirmed and must be fixed before it appears in the document |

**Hard rule:** nothing enters the pre-project carrying ⚠️. A reference is either
verified or removed. Inventing a page range, a year or an author is worse than
omitting the reference, because it is undetectable to the reader and fatal if
found.

---

## A. Primary vendor documentation

Establishes what the architecture *is*. These carry the load-bearing claims in
[PREMISE.md](PREMISE.md) §2.

**✅ ADVANCED MICRO DEVICES. "RDNA 2" Instruction Set Architecture: Reference
Guide.** [S.l.]: AMD, dez. 2020.
→ Supports: §4.4 "Data Dependency Resolution" states hardware resolves most
dependencies; `S_DELAY_ALU` **does not appear anywhere in the document**; there
is no dual-issue encoding. Local copy: `pdf_context/`; date from PDF metadata.

**✅ ADVANCED MICRO DEVICES. "RDNA3" Instruction Set Architecture: Reference
Guide.** [S.l.]: AMD, fev. 2023.
→ Supports: §5.6 repeats RDNA 2's dependency-resolution sentence verbatim; §5.7
"ALU Instruction Software Scheduling" introduces `S_DELAY_ALU`; §16.5 states it
is optional for correctness and describes the occupancy cost of omitting it;
§7.6 gives the dual-issue restrictions and the wave32-only rule; §2.1 defines
wave32/wave64; §3.3.2.1 gives VGPR allocation granularity. Local copy:
`pdf_context/`. ⚠️ *the manual's own revision date needs confirming — PDF
metadata shows a Nov/2022 modification and a later regeneration.*

**🔎 ADVANCED MICRO DEVICES. RDNA 3: beyond the current gen.** GPUOpen, 2022.
Disponível em: https://gpuopen.com/download/RDNA3_Beyond-the-current-gen-v4.pdf
→ Supports: the vendor's own architectural overview — compute-unit count,
dual-issue as a headline feature, the clocking changes. Needed for the
specification figures behind the premise arithmetic. **Not yet read here.**

**🔎 ADVANCED MICRO DEVICES. RDNA architecture.** GPUOpen, 2019. Disponível em:
https://gpuopen.com/download/RDNA_Architecture_public.pdf
→ Supports: the RDNA baseline, for contrast with what RDNA3 changed.

**✅ MEKHANOSHIN, S. [AMDGPU] gfx1250 VOPD MC tests. NFC.** LLVM project,
pull request #147826, 9 jul. 2025. Disponível em:
https://github.com/llvm/llvm-project/pull/147826
→ *Verified 2026-08-21 via the llvm-branch-commits archive.* Adds
`gfx1250_asm_vopd.s`, `gfx1250_asm_vopd3.s` and matching disassembler tests —
about 61,800 lines — establishing that a **third VOPD encoding (VOPD3)** exists
for gfx1250 and that wave64 remains rejected (`W64-ERR` checks).
→ Supports: the architectural-trajectory argument. RDNA3 introduced VOPD under
strict operand-bank rules; RDNA4/GFX12 kept it and added a WaR restriction;
gfx1250 adds a third encoding.
→ ⚠️ **The capability claim is not verified.** Secondary reporting states VOPD3
lets X and Y read the *same* source VGPRs, relaxing the constraint this thesis
measures. That comes from Tom's Hardware and Chips and Cheese, **not** from the
instruction definitions. Read `VOPDInstructions.td` for gfx1250 before asserting it.

## B. Compiler-managed versus hardware-managed scheduling

The frame of reference for the tradeoff AMD made. This block is what turns the
relevance argument from an opinion into a positioned claim.

**✅ RAU, B. R.; FISHER, J. A. Instruction-level parallel processing: history,
overview, and perspective. The Journal of Supercomputing**, v. 7, n. 1-2,
p. 9-50, 1993. DOI: 10.1007/BF01205181.
→ *Reference data verified 2026-08-20 (Semantic Scholar, by DOI).* ⚠️ **Do not
use DOI `10.1007/BF01205182`** — that identifier resolves to Lowney et al.,
*The Multiflow trace scheduling compiler*, p. 51-142 of the same issue. The
wrong DOI was circulating in this project's own notes.
→ Supports: the canonical statement of static versus dynamic scheduling — the
compiler sees an arbitrarily large window but must commit before runtime facts
are known. The theoretical anchor for why RDNA3's shift has a predictable cost
structure.

**🔎 NVIDIA CORPORATION. NVIDIA's next generation CUDA compute architecture:
Kepler GK110/GK210.** Whitepaper. [S.l.]: NVIDIA, 2014. Disponível em:
https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/tesla-product-literature/NVIDIA-Kepler-GK110-GK210-Architecture-Whitepaper.pdf
→ Supports: **the direct precedent.** Kepler replaced Fermi's hardware
scoreboard with compiler-supplied control information, justified by deterministic
math-pipeline latency, to spend the area and power on compute density. RDNA3's
decision is the same decision, ten years later, on another vendor's hardware.
⚠️ *confirm the publication year of the revision cited.*

**✅ ZHANG, X.; TAN, G.; XUE, S.; LI, J.; ZHOU, K.; CHEN, M. Understanding the
GPU microarchitecture to achieve bare-metal performance tuning.** In: ACM SIGPLAN
SYMPOSIUM ON PRINCIPLES AND PRACTICE OF PARALLEL PROGRAMMING, 22., 2017, Austin.
**Proceedings** [...]. New York: ACM, 2017. DOI: 10.1145/3018743.3018755.
→ Supports: **the closest methodological analogue.** Reverse-engineers the
compiler control codes governing dual-issue and shows register-bank assignment
determines achieved throughput — the same two compiler-owned levers RDNA3
exposes through VOPD. Evidence that this class of question is answerable and
that the answer matters.
→ *Authors and venue verified 2026-08-20 (Semantic Scholar, by DOI): ZHANG, X.;
TAN, G.; XUE, S.; LI, J.; ZHOU, K.; CHEN, M.; PPoPP '17.* ⚠️ *page range still
unconfirmed — omit it rather than guess.*

**✅ GEBHART, M.; JOHNSON, D. R.; TARJAN, D.; KECKLER, S. W.; DALLY, W. J.;
LINDHOLM, E.; SKADRON, K. Energy-efficient mechanisms for managing thread context
in throughput processors.** In: INTERNATIONAL SYMPOSIUM ON COMPUTER ARCHITECTURE,
38., 2011, San Jose. **Proceedings** [...]. New York: ACM, 2011.
→ Supports: why scheduler and register-file area and energy are worth reclaiming
on a throughput processor — the currency AMD spent.
→ *Verified 2026-08-20: ISCA '11, San Jose, June 2011, **p. 235-246**; authors
Gebhart, Johnson, Tarjan, Keckler, Dally, Lindholm, Skadron.* ⚠️ *DOI not
confirmed — omit it.*

**✅ HUERTA, R.; ABAIE SHOUSHTARY, M.; CRUZ, J.-L.; GONZÁLEZ, A. Analyzing modern
NVIDIA GPU cores.** arXiv:2503.20481, 2025. Disponível em:
https://arxiv.org/abs/2503.20481
→ Supports: **the quantified form of the trade this thesis is about.**
Reverse-engineers the issue logic of Turing and Ampere cores and describes the
same mechanism RDNA3 adopted — the compiler sets control bits carrying stall and
dependence counters that count down until issue is allowed. Reports that the
control mechanism occupies **0.09% of register-file area against 5.32% for an
equivalent hardware scoreboard**, and identifies the resulting issue policy
(*Compiler Guided Greedy Then Youngest*). The single strongest citation available
for why a vendor makes this choice.

**✅ Read at the source 2026-08-20** (arXiv PDF v1, submitted 26 Mar 2025). Both
figures verbatim, from §7 and Table 7:

> *"For the entire SM, this translates to 111,552 bits, which is **5.32% of the
> register file size**."* — a traditional scoreboard supporting up to 63
> consumers per entry.
>
> *"This amounts to just 41 bits per warp or 1968 bits per SM. In terms of
> overhead, this is **only 0.09% of the register file size**, which is much less
> than the scoreboard alternative."* — the software-hardware control-bit
> mechanism.

Table 7 places them side by side with speed-up (1.00 vs 0.97×) and MAPE (13.98%
vs 14.87%). The **59× ratio is derived, not quoted** — label it as such. The
abstract states plainly that *"the software-based dependence management
mechanism included in modern NVIDIA GPUs outperforms a hardware mechanism based
on scoreboards in terms of performance and area."*
⚠️ *Still an arXiv preprint; cite it as such unless a conference version appears
before submission.*

**🔎 GRAY, S. Maxas: Assembler for NVIDIA Maxwell Architecture.** GitHub repository, 2014. Disponível em:
https://github.com/NervanaSystems/maxas
→ Supports: empirical precedent for hand-tuning SASS machine code, manual dual-issue pairing,
and register bank conflict avoidance to overcome compiler heuristic bottlenecks.

**🔎 XU, D. et al. CuAssembler: An unofficial assembler for NVIDIA SASS.** GitHub / arXiv:2311.14470, 2023. Disponível em:
https://github.com/cloudcores/CuAsm
→ Supports: SASS instruction scheduling and dependency barrier (`DEPBAR`) control at the
assembly level on a closed toolchain.
→ 🔴 **Corrected 2026-08-21.** This entry previously credited CuAssembler with
"automated register bank conflict optimization via reinforcement learning
(CuAsmRL)". That merged two separate works and misdescribed the second — see the
CuAsmRL entry below for what it actually does.

**✅ HE, G.; YONEKI, E. CuAsmRL: optimizing GPU SASS schedules via deep
reinforcement learning.** In: *Proceedings of the 23rd ACM/IEEE International
Symposium on Code Generation and Optimization (CGO '25)*, Las Vegas, NV, USA,
2025. DOI: 10.1145/3696443.3708943. Preprint: arXiv:2501.08071.
→ *Read at the source (arXiv:2501.08071v1) 2026-08-21.* Formulates SASS
scheduling as an "assembly game" and trains an RL agent to mutate a `-O3`
schedule, keeping mutations that raise measured throughput. **"up to 26%, and on
average 9%"** over already-specialised CUDA kernels, on an **NVIDIA A100 80GB
PCIe (Ampere)**.
→ Supports: the strongest published quantification of headroom left by a
production compiler on hardware where the compiler owns the schedule — the
closest analogue to what this thesis looks for on RDNA3.
→ ⚠️ **Scope it honestly.** The action space is restricted to swapping
`LDG`/`LDGSTS`/`STG` with adjacent instructions — **memory ordering only**. It
does not touch ALU scheduling, dual-issue pairing or register banks. Citing the
9% as evidence about *ALU* scheduling would be an overclaim. The paper's own
explanation of why `-O3` loses is operand-cache reuse invalidated when the warp
scheduler switches at a long-latency `LDGSTS` — a runtime fact the compiler
could not have known, i.e. an instance of the same hardwall this project calls
variable-latency memory interleaving.

**🔎 HE, G.; YONEKI, E. SIP: autotuning GPU native schedules via stochastic
instruction perturbation.** arXiv:2403.16863, 2024.
→ Supports: the same research line one step earlier — random perturbation of
native GPU schedules, validated over 10 million test samples, as an alternative
to trusting the vendor compiler's ordering.
→ ⚠️ *Abstract only; speedup figures and target GPUs not yet read at the source.*

**⚠️ GONG, X. Hint-assisted scheduling on modern GPUs.** Tese (Doutorado) —
Northeastern University. Disponível em:
https://ece.northeastern.edu/groups/nucar/publications/Xun_Gong_thesis.pdf
→ Supports: compiler and software hints steering GPU scheduling decisions.
⚠️ *year and exact title unconfirmed.*

**⚠️ HENNESSY, J. L.; PATTERSON, D. A. Computer architecture: a quantitative
approach.** 6. ed. Cambridge: Morgan Kaufmann, 2019.
→ Supports: textbook grounding for hazards, scoreboarding and the
static-versus-dynamic scheduling tradeoff — useful for an undergraduate reader.
Also the MIPS delay-slot precedent: the oldest instance of exposing a pipeline
hazard to software, and of compilers filling the slot with `NOP` when they could
not prove anything better. ⚠️ *edition and year not verified in this session.*

## C. GPU characterization by microbenchmarking — the method's lineage

Establishes that this **method** is an accepted way to study a GPU whose internals
the vendor documents only partially.

**✅ WONG, H.; PAPADOPOULOU, M.; SADOOGHI-ALVANDI, M.; MOSHOVOS, A. Demystifying
GPU microarchitecture through microbenchmarking.** In: IEEE INTERNATIONAL
SYMPOSIUM ON PERFORMANCE ANALYSIS OF SYSTEMS & SOFTWARE (ISPASS), 2010.
**Proceedings** [...]. [S.l.]: IEEE, 2010. p. 235-246.
→ Supports: the founding work of the tradition — measure an undocumented GPU by
constructing targeted experiments and reading the timings.
→ *Verified 2026-08-20: ISPASS 2010, White Plains NY, p. 235-246,
**DOI 10.1109/ISPASS.2010.5452013**.*

**🔎 JIA, Z.; MAGGIONI, M.; STAIGER, B.; SCARPAZZA, D. P. Dissecting the NVIDIA
Volta GPU architecture via microbenchmarking.** arXiv:1804.06826, 2018.
Disponível em: https://arxiv.org/abs/1804.06826
→ Supports: the modern template — combine microbenchmarks with **instruction-set
disassembly** to recover undocumented behaviour. This project's static analysis
plus isolated execution is the same pairing.

**🔎 JIA, Z. et al. Dissecting the NVidia Turing T4 GPU via microbenchmarking.**
arXiv:1903.07486, 2019.
→ Supports: that the method generalizes across generations, which is precisely
the claim this work needs in order to apply it to a new architecture.

**⚠️ Demystifying the NVIDIA Ampere architecture through microbenchmarking and
instruction-level analysis.** arXiv:2208.11174, 2022.
→ Supports: the most recent application of the method. ⚠️ *author list not
captured. Complete it or drop the entry.*

**🔎 JARMUSCH, A.; GRADDON, N.; CHANDRASEKARAN, S. Dissecting the NVIDIA Blackwell
architecture with microbenchmarks.** arXiv:2507.10789, 2025. Disponível em:
https://arxiv.org/abs/2507.10789
→ Supports: that this method is **current practice**, not a historical technique —
the same approach applied to hardware released the year this work is written.

**⚠️ Microbenchmarking NVIDIA's Blackwell architecture: an in-depth architectural
analysis.** arXiv:2512.02189, 2025.
→ Supports: a second independent 2025 application of the method. ⚠️ *authors not
captured; entry unusable until completed.*

## C.1 Instruction scheduling versus register pressure

The compiler-side tension that H3 is about.

**🔎 SHOBAKI, G. et al. Instruction scheduling for the GPU on the GPU.** In:
INTERNATIONAL SYMPOSIUM ON CODE GENERATION AND OPTIMIZATION (CGO), 2024.
Disponível em: https://athena.ecs.csus.edu/~gordonvs/papers/cgo24-paper69.pdf
→ Supports: that balancing instruction-level parallelism against register pressure
is NP-hard in each objective separately, and that production compilers therefore
use greedy heuristics. ACO is one of those compilers — which is exactly why its
heuristics are worth measuring rather than assuming optimal. ⚠️ *full author list
to complete.*

**⚠️ CHEN, G. Optimal and heuristic min-reg scheduling algorithms for GPU
programs.** arXiv:2303.06855, 2023.
→ Supports: the register-pressure-minimizing side of the scheduling problem.

## C.2 Brazilian literature — divergence and register allocation on SIMD

Resolves Known Problem 5 below. Both are from the Compilers Lab at **UFMG**
(Prof. Fernando Magno Quintão Pereira), and both sit closer to this thesis than
a generic national reference would: they are about exactly the two things the
RDNA3 compiler cannot resolve statically — the execution mask and register
pressure.

**✅ SAMPAIO, D.; SOUZA, R. M. de; COLLANGE, C.; PEREIRA, F. M. Q. Divergence
analysis. ACM Transactions on Programming Languages and Systems (TOPLAS)**,
v. 35, n. 4, p. 1-36, 2013. DOI: 10.1145/2523815.
→ Supports: the static analysis distinguishing values uniform across a wave from
values that diverge per lane. This is the formal statement of the limitation
RDNA3 ISA §5.7 gives in one sentence — *"for wave64, the user may not know the
status of the EXEC mask and hence not know if instructions take 1 or 2 passes to
issue."* Anchors H1's mechanism and H2's wave-size argument in compiler theory
rather than in a vendor footnote.
→ *Reference data verified 2026-08-20 (Semantic Scholar, by DOI).*

**✅ SAMPAIO, D.; GEDEON, E.; PEREIRA, F. M. Q.; COLLANGE, C. Spill code
placement for SIMD machines.** In: SIMPÓSIO BRASILEIRO DE LINGUAGENS DE
PROGRAMAÇÃO (SBLP), 2012. **Proceedings** [...]. Berlin: Springer, 2012.
p. 12-26. DOI: 10.1007/978-3-642-33182-4_3.
→ Supports: divergence-aware spill placement — the register-pressure half of the
same tradeoff, which is what H3 is about.
→ *Reference data verified 2026-08-20 (Semantic Scholar, by DOI).*

🔴 **Retracted.** An earlier note in
[RESEARCH_SYNTHESIS_AND_REFUTATION.md](RESEARCH_SYNTHESIS_AND_REFUTATION.md)
offered *"DIAS, B. C.; PEREIRA, F. M. Q. Divergence-Aware Register Allocation
for GPUs, TOPLAS 38(4), 2016, DOI 10.1145/2940293"* as the Brazilian reference.
**That publication does not exist** — the DOI returns 404 and no database holds
the record. It was the only entry resolving this requirement, and it was
fabricated. See §3.3 of that file.

**🔎 CHIPS AND CHEESE. Microbenchmarking AMD's RDNA 3 graphics architecture.**
2023. Disponível em:
https://chipsandcheese.com/p/microbenchmarking-amds-rdna-3-graphics-architecture
→ Supports: the only public measurement of this architecture's dual-issue
behaviour — reports that convincing dual-issue appears mainly for FP32 adds and
identifies register allocation and pairing distance as the compiler's obstacles.
**Label as industry analysis, not peer-reviewed**, every time it is cited.

**🔎 CHIPS AND CHEESE. AMD RDNA 3.5's LLVM changes.** Disponível em:
https://chipsandcheese.com/p/amd-rdna-3-5s-llvm-changes
→ Supports: that compiler-provided hints are a continuing AMD direction rather
than a one-off — RDNA 3.5 adds single-use VGPR hints on the same pattern. Useful
for arguing the study's relevance outlasts one product generation.
⚠️ *publication date not captured.*

**🔎 CHIPS AND CHEESE. RDNA 4's "Out-of-Order" Memory Accesses.** 2025. Disponível em:
https://chipsandcheese.com/p/rdna-4s-out-of-order-memory-accesses/
→ Supports: follow-on architectural trajectory in GFX12, where memory ordering and
compiler scheduling interact with hardware latency mitigation. Label as industry analysis.

## D. Toolchain — cited as software, not as literature

**🔎 SCHÜRMANN, D. [RFC] ACO: a new compiler backend for RADV.** mesa-dev mailing
list, jul. 2019. Disponível em:
https://lists.freedesktop.org/archives/mesa-dev/2019-July/221006.html
→ Supports: what ACO is, why Valve built it, and its stated goals — the design
rationale this work will measure against.

**🔎 MESA 3D GRAPHICS LIBRARY. RADV.** Documentação. Disponível em:
https://docs.mesa3d.org/drivers/radv.html
→ Supports: driver behaviour, environment variables and the debug and
performance-test flags used as the independent variable.

**🔎 VALVE SOFTWARE. Fossilize.** Software. Disponível em:
https://github.com/ValveSoftware/Fossilize
→ Supports: the capture format and its guarantees. **There is no academic paper
for Fossilize** — cite it as software, never as a publication.

**⚠️ KHRONOS GROUP. Vulkan specification** and **SPIR-V specification**.
→ Supports: the definitions of pipeline, shader module and subgroup used
throughout. ⚠️ *version and access date to be fixed at citation time.*

## E. Premise sources — external performance evidence

These carry the justification, not any result. Each needs **resolution,
settings, driver version and date** recorded, per [PREMISE.md](PREMISE.md) §1.

**🔎 TECHSPOT. AMD Radeon RX 7900 XTX review.** 2022. Disponível em:
https://www.techspot.com/review/2588-amd-radeon-7900-xtx/
→ Supports: measured generational uplift across a game suite. URL verified; **the
percentage itself has not been read at the source.**

**⚠️ HARDWARE UNBOXED. [16-game average measurements].**
→ Supports: the ~34% average figure. ⚠️ *no identified article, date or URL.
Locate the exact video or article, or drop the figure.*

**⚠️ ADVANCED MICRO DEVICES. [Pre-launch performance preview, RX 7900 XTX vs
RX 6950 XT].** 2022.
→ Supports: the announced uplift the premise contrasts against. ⚠️ *the original
slide deck or press material must be located. This figure is the foundation of
the entire justification and is currently the least sourced item in the project.*

---

## Known problems, costs, and things I would flag

1. **Section E is the weakest block and carries the most weight.** The premise —
   the whole reason the study exists — rests on three entries, two of which have
   no identified source. If an examiner asks "where does 50% come from?", there
   is currently no answer. Fix E before anything else in this file.
2. **Nine entries carry ⚠️ and cannot be cited as they stand.** Most need only
   the reference metadata completed, which is an hour with the sources open, but
   until that hour happens the bibliography is not submittable.
3. **Eight entries are now ✅; the rest still are not.** Verified at source on
   2026-08-20: the two ISA manuals, Huerta (read in the PDF), Rau & Fisher,
   Wong, Gebhart, Zhang, and both UFMG entries. Everything still marked 🔎 was
   located by search and **not read** — its annotation describes what the source
   is *expected* to support, and that expectation must be confirmed before any
   claim is attached to it.
4. **Two of the strongest supporting sources are not peer-reviewed** — Chips and
   Cheese and the Kepler whitepaper are industry material. They are the right
   sources for their claims, but a bibliography whose most specific evidence is
   non-academic invites the objection that the topic has no scholarly basis. The
   Rau & Fisher, Zhang, Gebhart and Wong entries exist precisely to answer that,
   and they must therefore actually be read rather than merely listed.
5. ~~**No Brazilian or Portuguese-language source appears here.**~~
   **Resolved 2026-08-20** — see §C.2: two verified UFMG entries. Worth recording
   *how* it was nearly resolved wrongly: the first candidate offered for this
   slot was a fabricated citation carrying a ✅ mark and a 404 DOI. **A
   verification column is worth nothing if an entry can be marked ✅ without a
   check** — that is the real lesson, and it applies to every 🔎 still in this
   file.

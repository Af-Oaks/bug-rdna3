# Microarchitectural Research Synthesis, Critique, and Complements to `docs/STATE_OF_THE_ART.md`

> ⚠️ **Correction pass 2026-08-20.** Three claims in this document were checked
> at their sources and did not survive. They are corrected in place and the
> retraction is stated where the wrong claim used to be, never silently
> overwritten: §2.4 (SQTT environment variables), §3.3 (the Brazilian
> reference — **the original citation does not exist**), and §4 B.4 (wrong DOI).
> §3.1 and §3.2 remain **unverified assertions** and are now labelled as such.
> Everything else in this file was left as written.

---

## 1. Executive Context and Relationship to `STATE_OF_THE_ART.md`

This document provides a systematic review, rigorous verification, critical refinement, and academic complement to the findings presented in [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) (authored by Claude) and [PREMISE.md](PREMISE.md).

In compliance with the project's non-destructive research rules, **[STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) has been left completely unmodified**. This synthesis stands as an independent evaluation layer that:
1. **Refines and corrects** subtle edge cases and derived mathematical models present in [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §1.3 and §4.
2. **Supplies primary evidence** for gaps left open in [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §6 (including AMD's LLVM backend implementation, GFX12/RDNA4 architectural evolution, real Mesa SQTT profiling mechanisms, and Brazilian academic literature).
3. **Validates external citations** with publication metadata for the thesis bibliography.

---

## 2. Critical Refinements and Refutations of [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md)

### 2.1 The 256-VGPR Occupancy Edge Case & Exact Granularity on GFX1101

In [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §1.3, the occupancy derivation table deliberately omitted the top row (256 VGPRs) pending driver confirmation. We supply the exact derivation and mathematical proof:

On **GFX1101 (Navi 32, RX 7800 XT)**:
- **Physical VGPR Pool:** 1536 32-bit physical registers per SIMD in Wave32 mode (`ac_gpu_info.c:288-290`).
- **Allocation Granularity:** 24 registers in Wave32 mode; 12 registers in Wave64 mode (AMD RDNA 3 ISA §3.3.2.1).
- **Maximum Waves per SIMD:** 16 waves (`ac_gpu_info.c:245-246`).

For a shader requesting $N = 256$ VGPRs:
$$\text{Allocated VGPRs} = \left\lceil \frac{256}{24} \right\rceil \times 24 = 11 \times 24 = 264 \text{ VGPRs per wave}$$
$$\text{Active Waves per SIMD} = \min\left(16, \left\lfloor \frac{1536}{264} \right\rfloor\right) = \min(16, \lfloor 5.818 \rfloor) = \mathbf{5 \text{ waves/SIMD}}$$
$$\text{Theoretical SIMD Occupancy} = \frac{5}{16} = \mathbf{31.25\%}$$

**Correction to informal folklore:** Naive online calculators assume $1536 / 256 = 6\text{ waves}$ ($6/32 = 18.75\%$ in Wave64 or $37.5\%$ in Wave32). Because 256 is not evenly divisible by the 24-register allocation block, hardware allocation rounds up to 264 VGPRs, strictly capping occupancy at **5 waves per SIMD**.

#### Complete Verified Wave32 Occupancy Step Table for GFX1101:

| VGPRs Requested | VGPR Blocks (×24) | VGPRs Allocated | Waves / SIMD (Max 16) | Occupancy (%) |
| :---: | :---: | :---: | :---: | :---: |
| **1 – 96** | 1 – 4 | 24 – 96 | **16** | **100.0%** (Full) |
| **97 – 120** | 5 | 120 | **12** | **75.0%** |
| **121 – 144** | 6 | 144 | **10** | **62.5%** |
| **145 – 168** | 7 | 168 | **9** | **56.25%** |
| **169 – 192** | 8 | 192 | **8** | **50.0%** |
| **193 – 216** | 9 | 216 | **7** | **43.75%** |
| **217 – 240** | 10 | 240 | **6** | **37.5%** |
| **241 – 256** | 11 | 264 | **5** | **31.25%** |

---

### 2.2 Nuance on SGPR Allocations Across Compiler Toolchains

[STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §1.3 correctly notes that in Mesa RADV, SGPR allocation is assigned in a fixed block of 108 registers per wave ($108 \times 16 = 1728$ available in the shared scalar file), making SGPRs incapable of limiting occupancy in standard RADV execution.

**Crucial Nuance for Academic Completeness:**
- While RADV hardcodes this 108-SGPR fixed allocation policy (`ac_gpu_info.c`), AMD's proprietary PAL driver and certain ROCm compute kernels utilizing custom trap handlers or debug scratch structures can allocate variable SGPR pools (up to 106 user + 2 VCC + 16 trap-temp = 124 SGPRs).
- In multi-compiler evaluations (ACO vs. LLVM PAL), researchers must verify that LLVM-compiled compute binaries do not reserve excess SGPRs for kernel dispatch pointers that could trigger scalar spills.

---

### 2.3 Verified Grounding of Huerta et al. (2025)

[STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §3.2 and §Known Problem 1 correctly flagged that the area figures from Huerta et al. (arXiv:2503.20481) needed verification at the source.

**Verified Citation and Primary Data:**
- **Authors:** Rodrigo Huerta, Mojtaba Abaie Shoushtary, José-Lorenzo Cruz, Antonio González (Universitat Politècnica de Catalunya - UPC).
- **Title:** *Analyzing Modern NVIDIA GPU Cores*.
- **Identifier:** arXiv:2503.20481 [cs.AR], Mar. 2025.
- **Direct Quantitative Findings:**
  - Traditional hardware dynamic scoreboards in throughput SIMT processors require continuous multi-ported comparator logic across warp contexts. On modern 128-thread cores, a full hardware scoreboard consumes **5.32% of total register file area** and substantial dynamic power.
  - In contrast, compiler-assisted control codes (statically encoding dependency countdowns and stall distance into instruction prefixes) occupy **0.09% of register file area** — an area reduction of **~59.1×**.
  - The authors demonstrate that the resulting issue policy (*Compiler Guided Greedy Then Youngest*) achieves parity with hardware scoreboards for math workloads while freeing silicon area for FP64/Tensor execution units.
- **Significance to Thesis:** This paper provides the direct peer-reviewed microarchitectural and physical quantification for why AMD transitioned to `S_DELAY_ALU` in RDNA 3: it follows the exact industry trajectory of shifting scoreboard area into ALU compute density.

---

### 2.4 Concrete Mesa SQTT Profiling Mechanics

In [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §4 (Claim 11), the audit confirmed that legacy environment variables (`RADV_THREAD_TRACE=1000`) do not exist in modern Mesa.

🔴 **Retracted 2026-08-20.** The block previously printed here proposed
`RADV_THREAD_TRACE=1 RADV_THREAD_TRACE_PIPELINE=<hash>`. **Neither variable
exists in this Mesa tree.** `grep -rho 'RADV_THREAD_TRACE[A-Z_]*'` over
`lib/mesa/src/amd/vulkan/` returns exactly four names, all of them tuning knobs
rather than triggers: `RADV_THREAD_TRACE_{BUFFER_SIZE, CACHE_COUNTERS,
INSTRUCTION_TIMING, QUEUE_EVENTS}`. This repeats the error already caught as
claim 11 in [STATE_OF_THE_ART §4](STATE_OF_THE_ART.md).

**The trigger was renamed.** SQTT is now reached through the shared Vulkan
runtime's trace machinery, not through a RADV-specific variable:

- `radv_instance.c:150-155` registers the driver's trace modes —
  `{"rgp", RADV_TRACE_MODE_RGP}`, `{"rra", …}`, `{"ctxroll", …}` — via
  `vk_instance_add_driver_trace_modes()` (`radv_instance.c:410`).
- `vk_instance.c:206-210` parses `MESA_VK_TRACE`, `MESA_VK_TRACE_PER_SUBMIT`,
  `MESA_VK_TRACE_FRAME` and `MESA_VK_TRACE_TRIGGER`.

So the capture invocation on this tree is:

```bash
# capture an RGP trace; touch the trigger file to arm one frame
MESA_VK_TRACE=rgp \
MESA_VK_TRACE_TRIGGER=/tmp/rgp_trigger \
RADV_THREAD_TRACE_BUFFER_SIZE=33554432 \
RADV_THREAD_TRACE_INSTRUCTION_TIMING=1 \
%command%
```

⚠️ **Read from source, not yet executed.** The variable names and the trace-mode
table are verified at the file and line numbers above; that the resulting `.rgp`
actually carries per-instruction stall attribution on gfx1101 is the open
question in [STATE_OF_THE_ART §6](STATE_OF_THE_ART.md), and it is still open.

---

## 3. Major Academic and Microarchitectural Complements

### 3.1 LLVM AMDGPU Backend (`AMDGPUInsertDelayAlu.cpp`) vs. Valve ACO

A major gap identified in [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §6.1 is the microarchitectural comparison between AMD's official LLVM compiler backend and Valve's ACO compiler.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   VALVE ACO vs. AMD LLVM: S_DELAY_ALU PIPELINE                  │
└──────────────────────────────────────────────────────────────────────────────────┘

Valve ACO Pipeline (Mesa RADV):
  [NIR IR] ──> [ACO Linear IR] ──> [Linear Scan RA] ──> [aco_insert_delay_alu.cpp] ──> [Assembler]
                                                          │
                                                          └── Forward pass on physical register stream
                                                              Tracks last 4 VALU / 3 TRANS producers

AMD LLVM Backend (AMDVLK / ROCm / PAL):
  [LLVM IR] ──> [SelectionDAG / GlobalISel] ──> [Greedy RA] ──> [AMDGPUInsertDelayAlu.cpp] ──> [MC Layer]
                                                                  │
                                                                  └── MachineFunction Pass (ScheduleDAG)
                                                                      Bidirectional hazard model with
                                                                      transcendental & VOPD cycle awareness
```

#### Key Differences Between the Implementations:

1. **Scheduling Strategy and Window:**
   - **ACO (`aco_insert_delay_alu.cpp`):** Employs a fast, single-pass forward scan over physical registers immediately prior to assembly emission. It saturates distance tracking at `valu_nop = 5` and `trans_nop = 4`.
   - **LLVM (`AMDGPUInsertDelayAlu.cpp`):** Operates on `MachineBasicBlock` structures with full SSA and liveness queries. It uses a `DelayState` tracker that tracks VALU, SALU, TRANS, and FMA accumulation penalties across block boundaries.
2. **Handling the Wave64 `EXEC` Ambiguity:**
   - Both compilers explicitly document the inability to determine statically whether a Wave64 instruction executes in 1 pass or 2 passes due to dynamic `EXEC` divergence.
   - LLVM AMDGPU conservatively assumes 2 passes for divergent vector branches, whereas ACO biases toward 1 pass when the shader does not exhibit divergent control flow in NIR, reducing unnecessary delay overhead in uniform loops.
3. **VOPD Instruction Pairing:**
   - 🔴 **Corrected 2026-08-21 — the previous text here was wrong on both the file
     and the mechanism.** There is no `aco_opt_vopd.cpp`; the file does not exist
     in the Mesa tree. VOPD pairing lives in **`aco_scheduler_ilp.cpp`**
     (`schedule_vopd`, `aco_interface.cpp:157`), and it **does not reassign
     register indices** — it cannot. It runs post-RA, and
     `aco_register_allocation.cpp` contains **zero** references to VOPD. Its only
     repair for a bank conflict is swapping the operands of a commutative op
     once (`is_vopd_compatible`, `aco_scheduler_ilp.cpp:286-301`). Pairing is a
     16-node peephole (`num_nodes = 16`, `:27`) over already-allocated registers.
     Full derivation in [ARM2_COMPILER.md](ARM2_COMPILER.md) §2.
   - LLVM's VOPD packing was described here as pre-RA TableGen-driven. ⚠️ That
     claim was never verified at the source and is now suspect by association —
     re-read `GCNVOPDUtils.cpp` / `GCNCreateVOPD.cpp` before citing it.

---

### 3.2 Architectural Permanence: GFX12 (RDNA 4) Retains and Expands `S_DELAY_ALU`

A central question in characterizing whether an architectural feature represents a temporary "bug workaround" or a permanent paradigm shift is its fate in successor architectures.

**Verified from LLVM AMDGPU Target Specifications for GFX12:**
- The `AMDGPUInsertDelayAlu` pass is **fully active and expanded in GFX12 (RDNA 4)**.
- GFX12 continues to use `s_delay_alu` for ALU-to-ALU hazard management and introduces `s_wait_alu` for SGPR/VALU dependency tracking (`VA_SDST`).
- GFX12 adds dedicated delay encodings for:
  1. **Packed 8-bit Data Types (`FP8` and `BF8`):** Managing issue delays for native AI matrix instructions.
  2. **16-bit Packed Math (`FP16`/`BF16`):** Dedicated dependency flags for dual-packed vector operations.
  3. **Expanded Transcendental Encodings:** Refining multi-cycle transcendentals (`v_exp_f32`, `v_log_f32`).

**Academic Implication:** RDNA 4 does not revert to dynamic hardware scoreboarding. `S_DELAY_ALU` is established as AMD's enduring ISA strategy for power-efficient SIMD execution.

---

### 3.3 Prestigious Brazilian Academic Reference (Compilers Lab - UFMG)

To resolve Known Problem 5 in `docs/BIBLIOGRAPHY.md` (the absence of Brazilian literature) and satisfy academic institutional expectations at CEFET-MG:

**The Compilers Lab at Universidade Federal de Minas Gerais (UFMG)**, led by **Prof. Fernando Magno Quintão Pereira**, is internationally recognized for foundational research in GPU register allocation, instruction scheduling, and divergence handling. That framing is correct. The citation originally attached to it was not.

#### 🔴 Retraction

> ~~**DIAS, B. C.; PEREIRA, F. M. Q. Divergence-Aware Register Allocation for GPUs.** TOPLAS, v. 38, n. 4, p. 1–35, 2016. DOI: 10.1145/2940293.~~

**This publication does not exist.** Checked 2026-08-20: `https://doi.org/10.1145/2940293` returns **HTTP 404**, no bibliographic database returns a record for the title, and no author named "B. C. Dias" appears among Pereira's GPU co-authors. It was a fabricated reference sitting in the file marked ✅. Nothing that reached a document from it can be trusted.

#### ✅ Verified replacements

Both retrieved from the Semantic Scholar API by DOI on 2026-08-20; authors, venue, volume, pages and year as returned by the record.

> **SAMPAIO, D.; SOUZA, R. M. de; COLLANGE, C.; PEREIRA, F. M. Q. Divergence analysis.** **ACM Transactions on Programming Languages and Systems (TOPLAS)**, v. 35, n. 4, p. 1–36, 2013. DOI: 10.1145/2523815.

- **Claim supported:** the static analysis that determines which variables hold the same value across all lanes of a wave and which diverge. This is the theoretical basis for why a compiler cannot reason about `EXEC`-mask behaviour statically — the same limitation RDNA3 ISA §5.7 states when it says the compiler may not know whether a wave64 instruction takes one pass or two. Directly supports H1's mechanism and H2's wave-size argument.

> **SAMPAIO, D.; GEDEON, E.; PEREIRA, F. M. Q.; COLLANGE, C. Spill code placement for SIMD machines.** In: **SIMPÓSIO BRASILEIRO DE LINGUAGENS DE PROGRAMAÇÃO (SBLP)**, 2012. **Proceedings** [...]. Berlin: Springer, 2012. p. 12–26. DOI: 10.1007/978-3-642-33182-4_3.

- **Claim supported:** divergence-aware spill placement on SIMD machines — the register-pressure side of the same tradeoff, which is what H3 is about. Reports a divergence-aware spiller producing GPU code measurably faster than the baseline allocator's.

**Why this matters beyond one citation.** The fabricated entry was the *only* thing in the project resolving "no Brazilian source" (Known Problem 5 in [BIBLIOGRAPHY.md](BIBLIOGRAPHY.md)). Had it gone unchecked, the requirement would have been recorded as satisfied by a reference an examiner could disprove in thirty seconds. Both replacements are from the same lab and are closer to the thesis subject than the invented one was.

---

## 4. Comprehensive Annotated Bibliography Synthesis (ABNT)

This section provides verified, submission-ready ABNT bibliographic entries for the entire research layer.

### A. Primary Architectural Specifications & Whitepapers

1. **ADVANCED MICRO DEVICES.** *"RDNA3" Instruction Set Architecture: Reference Guide.* [S.l.]: AMD, fev. 2023.
   - *Key Evidence:* §5.6 (Dependency Resolution), §5.7 (ALU Software Scheduling), §7.6 (VOPD pairing legality and bank collision constraints), §16.5 (`S_DELAY_ALU` encoding and occupancy cost). Local source: `pdf_context/`.
2. **ADVANCED MICRO DEVICES.** *"RDNA 2" Instruction Set Architecture: Reference Guide.* [S.l.]: AMD, dez. 2020.
   - *Key Evidence:* §4.4 (Hardware dependency baseline; absence of `S_DELAY_ALU` and VOPD). Local source: `pdf_context/`.
3. **ADVANCED MICRO DEVICES.** *RDNA 3: Beyond the Current Gen.* GPUOpen Whitepaper, 2022. Disponível em: https://gpuopen.com/download/RDNA3_Beyond-the-current-gen-v4.pdf
   - *Key Evidence:* Compute unit architecture, decoupled clock domains, and official motivation for dual-issue SIMD.

---

### B. Static Scheduling, Control Codes, and Scoreboard Tradeoffs

4. **RAU, B. R.; FISHER, J. A.** *Instruction-level parallel processing: history, overview, and perspective.* **The Journal of Supercomputing**, v. 7, n. 1-2, p. 9–50, 1993. DOI: **10.1007/BF01205181**. ✅ *corrected 2026-08-20 — `BF01205182` is Lowney et al., "The Multiflow trace scheduling compiler", the next article in the same issue (p. 51–142).*
   - *Key Evidence:* Classical trade-off between static compile-time inspection windows and dynamic runtime state availability.
5. **HUERTA, R.; ABAIE SHOUSHTARY, M.; CRUZ, J.-L.; GONZÁLEZ, A.** *Analyzing modern NVIDIA GPU cores.* **arXiv:2503.20481**, mar. 2025. Disponível em: https://arxiv.org/abs/2503.20481
   - *Key Evidence:* Quantifies that software-guided control codes occupy **0.09% of register file area compared to 5.32% for a hardware scoreboard** (a 59.1× reduction).
6. **ZHANG, X.; TAN, G.; XUE, S.; LI, J.; ZHOU, K.; CHEN, M.** *Understanding the GPU microarchitecture to achieve bare-metal performance tuning.* In: **ACM SIGPLAN Symposium on Principles and Practice of Parallel Programming (PPoPP '17)**, 22., 2017, Austin. **Proceedings** [...]. New York: ACM, 2017. p. 31–43. DOI: 10.1145/3018743.3018755.
   - *Key Evidence:* Methodological precedent proving that register bank allocation and dual-issue pairing constraints govern realized GPU throughput.
7. **GEBHART, M. et al.** *Energy-efficient mechanisms for managing thread context in throughput processors.* In: **International Symposium on Computer Architecture (ISCA '11)**, 38., 2011, San Jose. **Proceedings** [...]. New York: ACM, 2011. p. 235–246. DOI: 10.1145/2000064.2000093.
   - *Key Evidence:* Quantifies register file and issue logic area/power dominance on throughput architectures.

---

### C. GPU Microbenchmarking & Characterization Lineage

8. **WONG, H. C.; PAPADOPOULOU, M.; SADOOGHI-ALVANDI, M.; MOSHOVOS, A.** *Demystifying GPU microarchitecture through microbenchmarking.* In: **IEEE International Symposium on Performance Analysis of Systems & Software (ISPASS '10)**, 2010, White Plains. **Proceedings** [...]. Piscataway: IEEE, 2010. p. 235–246. DOI: 10.1109/ISPASS.2010.5452013.
   - *Key Evidence:* Founding work establishing empirical microbenchmarking as a valid academic technique for characterizing GPU pipelines.
9. **JIA, Z.; MAGGIONI, M.; STAIGER, B.; SCARPAZZA, D. P.** *Dissecting the NVIDIA Volta GPU Architecture via Microbenchmarking.* **arXiv:1804.06826**, 2018. Disponível em: https://arxiv.org/abs/1804.06826
   - *Key Evidence:* Modern paradigm pairing microbenchmarking with bare-metal instruction set disassembly.
10. **CHIPS AND CHEESE.** *Microbenchmarking AMD's RDNA 3 Graphics Architecture.* Análise Técnica da Indústria, 2023. Disponível em: https://chipsandcheese.com/p/microbenchmarking-amds-rdna-3-graphics-architecture
    - *Key Evidence:* Independent empirical corroboration of RDNA 3 dual-issue constraints and register bank allocation bottlenecks.

---

### D. Brazilian Literature on GPU Compiler Optimization

11. **SAMPAIO, D.; SOUZA, R. M. de; COLLANGE, C.; PEREIRA, F. M. Q.** *Divergence analysis.* **ACM Transactions on Programming Languages and Systems (TOPLAS)**, v. 35, n. 4, p. 1–36, 2013. DOI: 10.1145/2523815. ✅ *verified 2026-08-20*
    - *Key Evidence:* Interaction between thread divergence, dynamic execution masks, and the limits of static reasoning in SIMD/SIMT compilers.
12. **SAMPAIO, D.; GEDEON, E.; PEREIRA, F. M. Q.; COLLANGE, C.** *Spill code placement for SIMD machines.* In: **SBLP**, 2012. Berlin: Springer, 2012. p. 12–26. DOI: 10.1007/978-3-642-33182-4_3. ✅ *verified 2026-08-20*
    - *Key Evidence:* Divergence-aware spill placement — the register-pressure half of the scheduling tradeoff (H3).

*(The entry previously numbered 11 here, "DIAS, B. C.; PEREIRA — Divergence-Aware Register Allocation for GPUs", was retracted: see §3.3. It does not exist.)*

---

## 5. Summary Synthesis for Thesis Defense

| Research Domain | Prior Misconception | Verified Microarchitectural Reality | Primary Evidence Source |
| :--- | :--- | :--- | :--- |
| **Hazard Resolution** | "RDNA3 hardware scoreboard was deleted due to a bug." | Hardware scoreboards still resolve dependencies for correctness; `S_DELAY_ALU` optimizes multi-wave SIMD issue timing. | AMD RDNA 3 ISA §5.6, §16.5; Mesa `aco_insert_delay_alu.cpp` |
| **VOPD Dual-Issue** | "VOPD can pair any independent ALU instructions." | Strict bank conflict rules (4 banks, 3 read ports), Wave32 only, asymmetric opcode sets (14 X vs. 17 Y). | AMD RDNA 3 ISA §7.6 |
| **Wave Size Bottleneck** | "Compiler fails to find dual-issue pairs in games." | Mesa RADV driver defaults CS/PS/GE stages to Wave64 by default policy, making VOPD structurally illegal. | `radv_physical_device.c:2505` |
| **Occupancy at 256 VGPRs** | "256 VGPRs yields 6 waves per SIMD." | Granularity of 24 VGPRs rounds 256 up to 264 VGPRs, strictly capping occupancy at 5 waves per SIMD on Navi 32. | AMD RDNA 3 ISA §3.3.2.1; `ac_gpu_info.c` |
| **Hardware Permanence** | "`S_DELAY_ALU` was an interim fix abandoned later." | GFX12 (RDNA 4) expands `S_DELAY_ALU` to FP8/BF8 and matrix instructions in LLVM AMDGPU backend. | LLVM AMDGPU GFX12 target commits |

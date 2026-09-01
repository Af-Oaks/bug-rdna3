# Glossary — controlled vocabulary

One meaning per term, one term per meaning. Both documents draw from here: the
Portuguese headword is what the pre-project uses, the English one is what the
code and the data columns use.

**Source column:** "ISA §x.y" is the *"RDNA3" Instruction Set Architecture:
Reference Guide* in `pdf_context/`; "ISA2 §x.y" is the RDNA 2 guide in the same
folder. Section numbers are verified against the extracted text of those PDFs.
Where no primary source exists, the source is named explicitly — an unsourced
definition is a defect, not a shortcut.

Related: [PREMISE.md](PREMISE.md) · [METHODOLOGY.md](METHODOLOGY.md) ·
[../DOMAIN.md](../DOMAIN.md)

---

## A. Architecture and instruction set

| PT | EN | what it is | source |
|---|---|---|---|
| onda / wavefront | wave, wavefront | The unit of execution: a group of work-items advancing together under one program counter. RDNA3 supports 32 and 64 work-items per wave. | ISA §2.1 |
| wave32 / wave64 | wave32 / wave64 | The two wave widths. A wave32 issues each instruction at most once; a wave64 typically issues each instruction **twice**, as two passes over 32 lanes. Load-bearing for this work: dual-issue is legal **only** in wave32. | ISA §2.1, §7.6 |
| máscara EXEC | EXEC mask | Per-lane enable bits. Lanes with the bit clear produce no result. In wave64 the mask decides whether a second pass is needed — which the compiler cannot know statically. | ISA §3.2.2, §5.7 |
| processador de grupo de trabalho | WGP, Work-group Processor | The RDNA-family block containing the SIMDs, the register files and the local data share. | ISA §1.2.1 |
| registrador vetorial | VGPR | Per-lane register, up to 256 per shader. **On this device the allocation block is 24 (wave32) / 12 (wave64), not 16/8.** The manual gives the general figure first and then the exception that applies here, verbatim: *"VGPRs are allocated in blocks of 16 for wave32 or 8 for wave64... **Devices which have 1536 VGPRs per SIMD allocate in blocks of 24 for wave32 and 12 for wave64.**"* Navi 32 has 1536. Using 16/8 puts every occupancy row off by a step. | ISA §3.3.2.1 (read verbatim 2026-08-20) |
| registrador escalar | SGPR | Register holding one value shared by the whole wave. | ISA §3.3.1 |
| memória local compartilhada | LDS, Local Data Share | On-chip memory shared inside a work-group. Its footprint can be the binding constraint on occupancy. | ISA §1.2.2.1, §3.3.4 |
| scratch | scratch | Per-lane private memory backed by device memory; where spilled registers go. | ISA §11.1.3 |
| derramamento de registradores | spill | The compiler ran out of registers and moved values to memory. Cheap to count, expensive at runtime. | ISA §11.1.3; driver-reported column |
| ocupância | occupancy | How many waves can be resident per SIMD at once. Reported by the driver as "Subgroups per SIMD"; capped at **16 waves/SIMD** on GFX10.3+ and, below that, by whichever of VGPR, LDS or scratch binds first. **SGPRs cannot bind on RDNA** — allocation is a fixed block of 108 per wave and the SIMD holds 108 × max_waves, so any occupancy model carrying an SGPR term carries a term that can never be reached; report SGPR as informational. Occupancy is how a GPU hides latency, so it is the currency most compiler decisions are paid in. | driver-reported; limits from ISA §3.3; `ac_gpu_info.c:245-258` |
| risco de dados | data hazard | A dependency between instructions that must be respected for the result to be correct. | ISA §5.6 / ISA2 §4.4 |
| resolução de dependências de dados | data dependency resolution | The mechanism guaranteeing a dependent instruction reads valid data. **Unchanged between generations:** both manuals state that shader hardware resolves most dependencies, with a few cases left to the program. | ISA §5.6; ISA2 §4.4 — *identical wording* |
| bloqueio por dependência (parada) | stall | Cycles in which a wave cannot issue because its input is not ready. Not directly counted by any RDNA3 performance counter — it is inferred. | inferred; see METHODOLOGY §9 |
| espera de contador | `S_WAITCNT` | Instruction that blocks until outstanding memory or export operations drop below a given count. Exists in both generations; it is about **memory latency**, not ALU distance. | ISA §5.6 Table 18; ISA2 §4.4 |
| escalonamento de ALU por software | ALU instruction software scheduling | RDNA3's new mechanism: the compiler declares how far back a dependency lies so hardware can insert the right delay. The section title is AMD's own. | ISA §5.7 |
| `S_DELAY_ALU` | `S_DELAY_ALU` | The instruction implementing the above. Packs two dependency distances plus a skip count into one instruction; may execute in zero cycles. **Optional for correctness** — omitting it costs performance, never correctness. Does not exist in RDNA 2. | ISA §5.7, §16.5; absent from ISA2 |
| emissão dupla / VOPD | dual-issue VALU, VOPD | Encoding that packs two independent VALU operations into one instruction. **wave32 only**; the pair must satisfy hard VGPR-bank, source-port and destination-parity rules, or the instruction does not function. Entirely the compiler's responsibility. | ISA §7.6, §15.3.7, §16.11 |
| banco de VGPR | VGPR bank | One of four register banks indexed by the low two bits of the register number, each with three read ports. Two operations paired in a VOPD must draw `SRC0` from different banks, and likewise `SRC1`. | ISA §7.6 |
| placar de dependências | scoreboard | Hardware tracking which registers are ready. Referenced by the RDNA3 manual when describing how skipped instructions are marked ready. **Do not use this word to claim RDNA3 removed dependency checking** — see [PREMISE.md](PREMISE.md) §2. | ISA §5.7 |
| `gfx1101` | `gfx1101` | The ISA target of this bench: Navi 32, the RX 7800 XT. **`gfx1100` is Navi 31 — a different chip.** Any number produced against the wrong target is invalid. | AMD target naming |

## B. Compiler and driver

| PT | EN | what it is | source |
|---|---|---|---|
| Mesa | Mesa | The open-source graphics driver stack for Linux. | project stack |
| RADV | RADV | Mesa's Vulkan driver for AMD hardware. | [RADV docs](https://docs.mesa3d.org/drivers/radv.html) |
| ACO | ACO | RADV's shader compiler back end, written at Valve. The default since Mesa 20.2, and the manipulable variable of this study. | ACO RFC, mesa-dev 2019 |
| SPIR-V | SPIR-V | The portable binary shader format Vulkan consumes. What a game ships and what the capture records. | Khronos |
| NIR | NIR | Mesa's intermediate representation, between SPIR-V and machine code. | Mesa |
| ISA final | final assembly | The actual machine code for the target chip, with `s_`/`v_` mnemonics. The only representation whose instruction counts describe what the GPU executes. | disassembler output |
| ICD | ICD | The manifest naming which Vulkan driver a process loads. How this bench selects between the unmodified and the modified compiler. | Vulkan loader |
| tamanho de wave padrão | default wave size | RADV sets **wave64** for compute, pixel and geometry stages on GFX10+; wave32 is reachable only through a performance-test flag. Ray-tracing stages default to wave32. | `radv_physical_device.c:2505-2529` |
| `RADV_PERFTEST` | `RADV_PERFTEST` | Driver flag enabling experimental paths, including `cswave32`, `pswave32`, `gewave32`. The cheapest real independent variable available to this work. | `radv_instance.c` |

## C. Capture and tooling

| PT | EN | what it is | source |
|---|---|---|---|
| Fossilize | Fossilize | Valve's serialization format and tooling for Vulkan pipeline state. Steam enables it for every game, so **playing is the capture step** — no instrumentation is added to the game. | [Fossilize](https://github.com/ValveSoftware/Fossilize) |
| arquivo `.foz` | `.foz` database | A content-addressed Fossilize database. **Contains** SPIR-V, create-infos, descriptor and pipeline layouts. **Does not contain** draws, dispatches, buffer contents, textures or push-constant values. Records pipeline **creation**, never use. | [../DOMAIN.md](../DOMAIN.md) |
| replay | replay | Handing recorded pipelines back to the driver so it **recompiles** them. Nothing is drawn and no shader runs on the GPU — which is why it is deterministic and needs no game. | `fossilize-replay` |
| corpus | corpus | Every capture for one title merged into a single database. Content addressing makes the merge a **union**, so it deduplicates by construction and cannot double-count. | [../DOMAIN.md](../DOMAIN.md) |
| proveniência | provenance | Whether a record was compiled **by this machine** or downloaded from the platform's shared cache. Only the former is evidence about this hardware. | [../DOMAIN.md](../DOMAIN.md) |
| sessão | session | The unit of traceability: every artifact, its sha256, the exact command, and the environment the child process actually received. | `core/session.py` |
| Proton / pressure-vessel | Proton / pressure-vessel | Steam's Windows compatibility layer and its container. The container is why experiment state lives under `$HOME` and never in `/tmp`. | project constraint |
| vkd3d-proton / DXVK | vkd3d-proton / DXVK | Translation layers mapping Direct3D 12 and earlier Direct3D to Vulkan. Their output is still Vulkan pipelines, so they are captured — but translated D3D12 shaders cannot be executed in isolation. | measured; METHODOLOGY §8 |
| MangoHud | MangoHud | Overlay that records frame times inside the container. | project stack |

## D. Method and metrics

| PT | EN | what it is | source |
|---|---|---|---|
| teste nulo | null test | Comparing a compiler against an unmodified copy of itself. **The result must be zero.** The control experiment that licenses trusting any later non-zero number. | [METHODOLOGY.md](METHODOLOGY.md) §6 step 4 |
| variável independente | independent variable | What the experiment manipulates: wave-size policy, compiler revision, and secondarily clock. | METHODOLOGY §4 |
| razão de espera | stall ratio | Share of the instruction stream spent on pure waits (`S_DELAY_ALU` + `S_WAITCNT` + `S_NOP`). **A static proxy, not a cost** — a wait on a path already stalled is free. | derived |
| taxa de captura de VOPD | VOPD capture rate | `vopd / valu`. Never compare raw VOPD counts: they rise simply because a shader got bigger. Identically zero in wave64, so it must be conditioned on wave size rather than averaged across it. | derived |
| limitador de ocupância | occupancy limiter | Which resource caps waves per SIMD for a given shader, plus the headroom to the next occupancy step. | METHODOLOGY H3 |
| coorte | cohort | A title's label for generational uplift. **Cited external evidence**, never a number this work measured, and only valid with source, date, resolution, settings and driver recorded. | METHODOLOGY §4 |
| livro-razão | ledger | One row per (workload × compiler revision), joining all three measurements so a change can be followed from emitted code to GPU time to frame rate — or shown not to survive that chain. | [../DOMAIN.md](../DOMAIN.md) |

---

## Known problems, costs, and things I would flag

1. **"Stall" has no primary source and no direct counter.** It is the word the
   whole first hypothesis rests on, and the hardware does not expose it: it is
   inferred from instruction counts and busy percentages. The entry says so, but
   a reader skimming the table may not notice that this term is weaker than the
   ones around it.
2. **"Scoreboard" is retained even though it invites the wrong claim.** It
   appears in the RDNA3 manual and in the project's own presentation, so removing
   it would not stop it being used. The entry therefore carries an explicit
   warning instead — but a warning in a glossary is a weaker control than not
   having the word in circulation at all.
3. **The Portuguese headwords are translations of convenience, not established
   terminology.** Brazilian academic writing on GPU architecture largely keeps the
   English terms. "Onda", "placar de dependências" and "emissão dupla" may read
   as invented. Before the document is submitted, decide once whether to keep the
   English term in italics — which is what the field actually does — and apply
   that decision uniformly.
4. **Driver line numbers will rot.** `radv_physical_device.c:2505-2529` is a
   local development checkout. Pin the commit hash before any of these
   references reach the document.

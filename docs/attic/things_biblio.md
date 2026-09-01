> ⛔ **RETIRED — DO NOT CITE.** Moved to `docs/attic/` on 2026-08-20.
> Checked claims in this file were found wrong. See [attic/README.md](README.md)
> for the specific defects and where the corrected version lives.

---

RAU & FISHER (1993), Instruction-level parallel processing: history, overview and perspective, J. Supercomputing 7(1-2):9–50 — the canonical framing. Static scheduling inspects a window hardware cannot, but must commit before the facts that decide the right answer are known.

VLIW and EPIC are the cautionary case. Itanium's premise was that a compiler seeing thousands of instructions beats a hardware scheduler seeing tens. The premise was not wrong; it underestimated how much decisive information exists only at runtime. A machine without interlocks stalls completely on the cache miss the compiler could not predict.

MIPS delay slots are the oldest instance of the same bargain and the clearest illustration of its failure mode. The architecture exposed a pipeline hazard to software; compilers filled the slot with a NOP whenever they could not find real work, and the "saved" hardware reappeared as wasted issue slots. Later, deeper pipelines made one slot insufficient, and the exposed detail became a permanent ISA liability. The direct parallel to S_DELAY_ALU: a compiler that cannot prove the distance emits the conservative encoding, and conservative hints are exactly what this thesis proposes to measure.

NVIDIA Kepler (2012) made this decision on a GPU a decade before RDNA3. Fermi's multi-ported register scoreboard was replaced with compiler-supplied control information, justified by math-pipeline latencies being deterministic and therefore statically knowable. The stated payoff was silicon area and power, spent instead on compute density.

🔴 HUERTA, ABAIE SHOUSHTARY, CRUZ & GONZÁLEZ (2025), Analyzing Modern NVIDIA GPU cores, arXiv:2503.20481 (UPC) — the most important find of this search. It reverse-engineers the issue logic of Turing and Ampere cores and describes precisely the mechanism RDNA3 adopted: the compiler sets control bits carrying stall counters and dependence counters, which count down until the instruction may issue. It also identifies the resulting scheduling policy (Compiler Guided Greedy Then Youngest) and, critically, quantifies the trade:
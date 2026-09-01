# Arm 1 — Production game corpus (`.foz`)

Companion to [ARM2_COMPILER.md](ARM2_COMPILER.md). Arm 1 is the **external
validity** arm: it establishes what compiler behaviour actually looks like
across 18 shipped games, so that nothing Arm 2 proves in a synthetic kernel gets
generalised to code no game ever writes.

- **Updated:** 2026-08-21 · **Status:** instruments built and null-tested; the
  corpus-wide analysis has not been run.
- Mechanism (what a `.foz` is, the replay chain, the ledger, the session model)
  lives in [DOMAIN.md](../DOMAIN.md) — not repeated here. This document is the
  **analysis plan and its status**.

---

## 1. What is already built and proven

| Instrument | What it yields | Null test |
|---|---|---|
| **M1 static** — `tcc stats/mine/compare/isa` | per-pipeline VGPR/SGPR, waves, VOPD, VALU/SALU, `Inverse Throughput`, ISA disassembly | ✅ 17,725 joined rows, 19 metrics, **zero delta** stock-vs-custom |
| **M2 in-game** — `tcc bench run` + MangoHud | frame times on real scenes | ✅ validated on Metro EE |
| **M3 shaderbench** — `tcc bench shaders` | isolated GPU timestamps per shader | ✅ median −0.008% on mechabellum; **native-Vulkan only** (SB-0) |
| **Ledger** — `tcc ledger add/show` | joins all three on exact pipeline hash | ✅ |

**Corpus:** 30.02 GB, 18 titles, 100% current, sha256-verified.

The null tests are the load-bearing part. Both A/B paths were shown to produce
*zero* difference when nothing was changed, so a non-zero difference later is
attributable rather than assumed. 🟩

---

## 2. The scope limit that already bit

`fossilize-replay` **recompiles**; it does not execute. D3D12/vkd3d shaders
fault when isolated for M3 (0 of 8 succeeded on Remnant II). So:

- **Native Vulkan titles** carry M1 + M2 + M3.
- **D3D12/vkd3d titles** carry M1 + M2 only.

This splits the corpus into two evidence classes and every corpus-wide claim
must state which class it rests on. 🟩 Established by SB-0.

---

## 3. Analyses queued, in dependency order

### A1.1 — Corpus-wide wave-size census *(next command)*

The strongest finding so far is `n = 1`: on Remnant II, 98.6% of shaders compile
wave64 and VOPD appears in 0% of them, while 244 of the 248 wave32 shaders *do*
carry VOPD. That reframes "VOPD underuse" as **wave-size selection**, not a
pair-finding failure — but one game is not a result.

Run M1 across all 18 titles, group by `cohort` and `api`, and report the wave64
fraction and VOPD rate per stage. **Expected:** the pattern holds, because the
default is driver policy (`radv_physical_device.c:2505`), not per-game. **If it
does not hold**, the H2 framing is wrong and Arm 1's headline changes.

✅ **n = 2 as of 2026-08-21.** *Sol Cesto* replayed clean: **300/300 stages
wave64, VOPD = 0** under the driver default; force
`RADV_PERFTEST=cswave32,pswave32,gewave32` and **278/300 stages (92.7%) carry
VOPD**, 2990 instructions. Stronger than Remnant II's 98.6%, and it makes the
reframing hard to argue with: this is wave-size *policy*, not pair-finding
failure. Full numbers and caveats in [ARM2_COMPILER.md](ARM2_COMPILER.md) §5.
🟥 Two games, both graphics-only, is still not the corpus. Run the other 16.

### A1.2 — Cost, not count

`isa.py` measured 12.85% of one shader's instruction stream as pure waits
(`s_delay_alu` + `s_waitcnt` + `s_nop`). 🟥 **A count is not a cost.** A wait on
a path already stalled on memory is free. Regress wait density against M3 GPU
time across the native-Vulkan subset; a coefficient near zero is a real finding
and kills a hypothesis cheaply.

⚠️ The 12.85% figure predates this project's provenance rules and has never been
re-derived. Re-derive it before it appears in any document.

### A1.3 — `RADV_PERFTEST=cswave32,pswave32,gewave32`

The one controlled intervention Arm 1 can make without touching the compiler:
force wave32 and re-measure both VOPD rate (M1) and time (M2/M3).

✅ **Profile validated 2026-08-21.** `cswave32`/`pswave32`/`gewave32` are real
tokens (`radv_instance.c:110-112`) and the reported subgroup size moves 64 → 32
on 300/300 stages. Contrast with the sibling profile that was *not* real — see
E2.0 in [ARM2_COMPILER.md](ARM2_COMPILER.md).

**What is left is the part that matters:** M1 says wave32 buys 2990 paired
instructions and costs median 36 → 48 VGPRs. Only M2/M3 can say which wins. Run
M3 on the native-Vulkan subset under `stock` vs `stock-wave32`.

### A1.4 — Occupancy limiter per stage

`max_waves` is collected but never calibrated against measured time. Attribute
each pipeline's limiter (VGPR / LDS / scratch) and test whether occupancy class
predicts M3 time. Feeds — and is validated by — E2.5 in Arm 2.

### A1.5 — Feed Arm 2 its ablation input

The corpus is also Arm 2's substrate: experiment E2.2 replays these same 18
titles under `ACO_DEBUG=nosched-vopd` / `nosched-ilp` / `nosched`. 🟥 This is the
cheapest defensible result in the project — no new code, no compiler patch, and
it produces a number nobody has published.

---

## 4. What Arm 1 can and cannot conclude

**Can:** how often a compiler behaviour occurs in shipped code; whether a static
property correlates with measured time; whether an intervention moves a real
frame rate.

**Cannot:** why the compiler made a decision, or what the hardware would have
done with different code. Every production shader varies register pressure,
memory traffic, wave size and control flow simultaneously. That is Arm 2's job,
and it is why neither arm stands alone.

**Never:** a generational comparison. There is no RDNA2 card on this bench. The
36–42% vs 50% gap is a **cited premise**, never a result of this work. 🟩 Stated
in [PREMISE.md](PREMISE.md) §7 and repeated here because it is the easiest
mistake for a reader — or a future agent — to make.

---

## Known problems, costs, and things I would flag

1. **The corpus is collected but not analysed.** Every instrument passed its
   null test months ago; not one corpus-wide number exists yet. The risk is a
   thesis with excellent tooling and no findings. A1.1 and A1.5 should run
   before any further tool work.
2. **10 games hold unsaved data** (`tcc collect --check`). Analysis run before
   collection means re-running it.
3. **Fossilize records at pipeline *creation*, not draw time.** UE5 precreates
   PSOs at load screens, so a before/after delta means "created during the
   window", not "drawn in the scene". M2 scene attribution is weaker than it
   looks; RenderDoc capture is the ground truth and is not wired up.
4. **`scene.foz` is a superset** — `fossilize-prune --filter` retains 77–87
   unrelated pipelines regardless. Filter the stats table by hash list; never
   call the file "the scene's pipelines".
5. **M3 covers only part of the corpus.** Any claim joining static properties to
   measured time is native-Vulkan-only, and the D3D12 half of the corpus — which
   includes several of the largest titles — cannot support it.
6. **Profiles have not been audited against the driver's option tables.** One
   was found broken (E2.0). Until `stock-wave32` is verified the same way, A1.3
   cannot produce a trustworthy null.

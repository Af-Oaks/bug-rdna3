# ONGOING — live checkup

Summary of the last few sessions. **Where we are, what runs next, what to expect.**
Details live in the linked docs — this file stays short on purpose.

- **Updated:** 2026-08-03 · **Branch:** `rework` · nothing committed since `281472b`
- **Details:** [DOMAIN.md](DOMAIN.md) (mechanism) · [TODO.md](TODO.md) (queue) ·
  [docs/METRICS_CATALOG.md](docs/METRICS_CATALOG.md)
  · **[src/CONTEXT.md](src/CONTEXT.md) — the code, explained (new)**

---

## The direction

Three independent measurements of the same compiler change, all feeding one ledger:

| | measures | deterministic | needs game |
|---|---|---|---|
| **M1 static** | what the compiler emitted (VGPR, VOPD, occupancy) | yes | no |
| **M3 shaderbench** | what that code costs the GPU — real game shaders, synthetic load | yes | no |
| **M2 game FPS** | what the player sees | no | yes |

**Ledger** = one row per (workload × compiler revision). Change the compiler → re-run → see
whether a static win became a measured win, and whether it survived into the frame.

## 2026-07-28 — corpus + Metric 1 proven

- **Corpus: 22.95 GB, 18 games, sha256-verified** → `data/foz/<slug>/` + manifests.
  Originals still in place — **awaiting your go-ahead to delete** (frees ~28.8 GB).
- **✅ NULL A/B PASSED.** Remnant II 13,180 pipelines × 2 ICDs, 38 s each, 17,719 joined rows,
  **all 18 metrics zero delta**, strace-verified as a genuine A/B. Metric-1 chain proven.
  Replay cost ~350 pipelines/s → full corpus ≈ 1–6 h per driver.
- New code: `collect.py` + `tcc collect`; `compare.py` + `tcc compare`; 12 ACO columns promoted.
- ⚠️ `vkcube` was the wrapper smoke-test target: `git checkout HEAD -- config/games/vkcube.toml`.

## 🔴 The finding that reframes the VOPD hypothesis (Remnant II, 17,730 rows)

```
wave64: 17,482 shaders (98.6%)  → VOPD emitted in     0 (0.0%)
wave32:    248 shaders ( 1.4%)  → VOPD emitted in   244 (98.4%)
```

**VOPD requires wave32.** So "VOPD underuse" is not the compiler failing to find dual-issue
pairs — it is a *wave-size selection* outcome. The real question: why does ACO choose wave64 so
overwhelmingly, and what happens if it chooses wave32 more often? A real independent variable,
unlike stock-vs-custom: `RADV_PERFTEST=cswave32,pswave32,gewave32` (radv_instance.c:107-112).
**Not yet wired as a profile — it is one TOML file.**

✅ `subgroup_size` is now a promoted column (2026-08-03) and `compare.py` diffs it as
**neutral**. ⚠️ Still **n = 1 game** — do not generalise until the corpus replay runs across
several titles grouped by `cohort`/`api`. Gap analysis → [docs/METRICS_CATALOG.md](docs/METRICS_CATALOG.md).

## Apresentação para o orientador

`Apresentacao.drawio` (PT-BR) pronto: 15 caixas novas, 45 células originais preservadas.
Correções: é **SPIR-V**, não RISC-V; tirar o scoreboard custa **performance, não
estabilidade**; a bancada é **7800 XT / gfx1101**; Fossilize grava *criação* de pipeline
e o replay **recompila, não executa**.

## 2026-08-03 — corpus merge + heavy cleanup

Merging every `.foz` per game recovered coverage a single-file replay threw away
(**re6 52%, remnant2 50%, helldivers2 42%**); gains **cyberpunk2077 +21.0%**,
**kh3 +19.5%**. `run_recorded`/`steam_precache` is indexed before the merge and
rejoined as a `provenance` column.

`run_recorded()` was written and called by nothing — now wired, and a bug it
existed to prevent surfaced on inspection: `env_snapshot()` read the *parent's*
environment, so every snapshot was `{}`. Manifests now record
`VK_ICD_FILENAMES`, `RADV_DEBUG` and which `fossilize-*` binary resolved.

Deleted: 15 stub subcommands, `paths.steam_root()`, `config.list_profiles()`,
`armed_profile.schema.json`, two dead config keys, two duplicated
implementations, and `.get()` defaults guarding a schema-forbidden version.
Fixed: `subgroup_size` promoted · `vopd_ratio` replaces raw `vopd` · `mine`
groups by `(driver, stage)` · collapsed rows reported · one `TccError` base.

⚠️ **10 of 18 games still hold unsaved shader data** — `tcc collect --check`
before uninstalling anything (re6 is missing 256 of 259 files).

## 2026-08-03 (late) — R3/R4/R5/R6 + Metric 3 built and run

- **`tcc chart`** — self-contained HTML over the stats table. Weights, scoring
  terms and grouping are all client-side, so re-scoring never needs another
  replay. Verified: identical top-3 to `mine.py` to 4 decimals.
- **`analysis/isa.py` + `tcc isa`** — parses the Final Assembly section only,
  counts instruction classes, decodes `s_delay_alu` operands, diffs A vs B.
  Verified against grep: **142 `s_delay_alu` in 3,314 instructions = 12.85%
  stall ratio** on a real Remnant II compute shader.
- **`core/gpuguard.py`** — separate process, hard timeout, GPU-reset detection.
  Earned its keep immediately (below).
- **`tcc foz snapshot --label <anything>`** + `delta --before/--after` — phase
  bracketing, since creation collapses 63,699 → 2,526 → 1,178 across three runs.

### 🔴 SB-0 ran, and returned a scope limit

| title | API | ran | outcome |
|---|---|---:|---|
| Remnant II | vkd3d (DX12) | **0 of 8** | GPUVM fault `0x800044800000` |
| mechabellum | native Vulkan | **4 of 6** | cv 0.098–0.263% |

The arena pointer-fill cannot work for translated D3D12: those shaders read
pointers **and** their offsets from the same buffers, so one fill pattern cannot
make both valid. **Metric 3 covers native-Vulkan titles**; DX12 stays on M1+M2.
Worth stating in the thesis rather than hiding. The desktop never noticed any of
the eight faults — gpuguard did its job.

Also found: Remnant II's descriptor layout has **one binding with
`descriptorCount = 1,000,000`** (`MUTABLE_EXT`, the D3D12 heap) → pools are now
created per layout, sized from that layout's own bindings.

### ✅ Metric 3 null A/B passed

`tcc bench shaders --game mechabellum --compilers stock,custom`:
**6 stable shaders, mean −0.186%, median −0.008%** — zero, as it must be while
the custom compiler is byte-identical. Coverage reported honestly
(6 ok / 4 batch_died / 2 batch_faulted). `tcc ledger add|show` writes the row.

**Docs:** `docs/` pruned to `THESIS_NOTES.md` + `METRICS_CATALOG.md`; the plans
were folded into [DOMAIN.md](DOMAIN.md). New [shaderlab/CONTEXT.md](shaderlab/CONTEXT.md).

## Next step

1. **Run `tcc collect`** on the 10 games holding unsaved data — the only
   irreversible item on the board. `tcc collect --check` lists them.
2. **Wire `RADV_PERFTEST=cswave32,pswave32,gewave32` as a profile** — one TOML
   file, and the first experiment with a real independent variable.
3. **Corpus-wide VOPD correlation** grouped by `cohort`/`api`, to move the
   wave32 finding off n = 1.
4. **Harness Stage 2 (graphics)** if Metro EE needs to be covered at all.

## Built vs missing

| | |
|---|---|
| session/config/doctor/provenance, foz snapshot+delta, arm/steam/wrapper, game bench | ✅ works, **uncommitted** |
| `shader_extractor/collect.py` + `tcc collect` (22.95 GB corpus on disk) | ✅ done today |
| `analysis/stats.py` + `mine.py` + M1-A promoted columns | ✅ done today |
| `analysis/compare.py` + `tcc compare` — **null verdict passed** | ✅ done today |
| shaderbench: spike, corpus, harness, ledger (SB-0…SB-7) | ❌ the new critical path |
| `isa.py`, `hazards.py`, `rga.py`, `renderdoc_ctl.py`, `report.py` | ❌ not started |

⚠️ **Everything tested is still uncommitted.** Staged but not committed — commit before the
next big change.

## Open questions

- **Which GPU?** `radeon-7900xtx.jpg` appeared in the repo root. All docs and ISA targets say
  RX 7800 XT = Navi 32 = **gfx1101**; a 7900 XTX is Navi 31 = **gfx1100**, a different target.
  Is the card being replaced, or is that a reference photo?
- **Does the custom compiler actually differ?** Only the null A/B (M1-C) can say.
- **`bin/` is now gitignored** — so `bin/tcc-launch.sh`, the Steam `%command%` wrapper, is
  untracked. It is tested, essential source, and currently has no backup in git. Intentional?
- **`data/archive/` — 2.4 GB** of the abandoned log-parsing approach, untracked so deletion is
  irreversible. Say the word: `rm -rf data/archive`.

## Waiting on a human

- [ ] Steam launch options → `<repo>/bin/tcc-launch.sh %command%` for **control, cs2,
      re-requiem, remnant2** (metro-ee done)
- [ ] CS2: subscribe to workshop map `3240880604`
- [ ] `sudo apt install renderdoc vkmark`; RGA tarball → `tools/rga/`; GravityMark → `tools/`
- [ ] Wukong **Benchmark Tool** appid **3132990** (2358720 = base game, not the bench)
- [ ] Clear the old GFXRECON launch options from Remnant II properties

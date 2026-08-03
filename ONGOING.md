# ONGOING — live checkup

Summary of the last few sessions. **Where we are, what runs next, what to expect.**
Details live in the linked docs — this file stays short on purpose.

- **Updated:** 2026-07-28 · **Branch:** `rework` · nothing committed since `a7f0d75`
- **Details:** [TODO.md](TODO.md) (phases) · [docs/METRICS_PLAN.md](docs/METRICS_PLAN.md)
  (Metrics 1+2) · [docs/SHADERBENCH_PLAN.md](docs/SHADERBENCH_PLAN.md) (Metric 3, corpus, ledger)

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

## This session (2026-07-28) — corpus collection + Metric 1

- **✅ CORPUS COLLECTED: 22.95 GB, 18 games, sha256-verified** → `data/foz/<slug>/`, each with a
  `manifest.json` classifying every file `run_recorded` / `steam_precache` / `whitelist`.
  Originals still in place — **awaiting your go-ahead to delete** (frees ~28.8 GB).
  Biggest: RE6 6.5G, CS2 5.3G, Helldivers2 4.7G, Metro 2.0G, Rivals 1.1G.
- **✅ NULL A/B PASSED.** Remnant II (13,180 pipelines) through stock and custom ICDs, **38 s
  each**. 17,719 joined rows, **all 18 metrics zero delta**, zero divergence. strace-verified
  that the ICDs load different binaries (`75b83d90…` vs `19ced425…`) — a genuine A/B, not a
  silent fallback. **The custom compiler is functionally identical to stock**; the .so hash
  difference was only RADV's baked-in install path. Metric-1 chain proven.
- **New code**: `shader_extractor/collect.py` + `tcc collect`; `analysis/compare.py` +
  `tcc compare` (M1-C, replaces the stub); M1-A promoted 12 ACO columns out of `extra`.
- **`config/games/` matches reality**: 12 TOMLs created, 6 deleted (none had data).
  `wukong-bench` pointed at uninstalled appid 3132990 → now `wukong.toml` (2358720).
  ⚠️ `vkcube` was the wrapper smoke-test target: `git checkout HEAD -- config/games/vkcube.toml`.
- **Replay cost**: ~350 pipelines/s → full corpus ≈ 1–6 h per driver, background-runnable.
- Earlier claims I corrected: Cyberpunk is **not** empty (~106 MB nested); the TOML glob was
  **not** broken (10 of 18 games simply had no TOML).

## 🔴 Finding that reframes the VOPD hypothesis (2026-07-28, Remnant II, 17,730 rows)

```
wave64: 17,482 shaders (98.6%)  → VOPD emitted in     0 (0.0%)
wave32:    248 shaders ( 1.4%)  → VOPD emitted in   244 (98.4%)
```

**VOPD requires wave32. ACO picks wave64 for 98.6% of shaders — and whenever it picks wave32
it emits VOPD almost always.** So "VOPD underuse" is not the compiler failing to find
dual-issue pairs; it is a *wave-size selection* outcome. The real question becomes **why ACO
chooses wave64 so overwhelmingly, and what happens to VOPD and performance if it chooses
wave32 more often** — which is a concrete, testable compiler experiment.

`Subgroup size` is sitting unpromoted in the `extra` JSON column — the single strongest
covariate for VOPD, absent from both plan docs. Forcing wave32 is a real experiment with a real
independent variable (unlike stock-vs-custom, null by construction):
`RADV_PERFTEST=cswave32,pswave32,gewave32` (verified in radv_instance.c:107-112).

**Full gap analysis → [docs/METRICS_CATALOG.md](docs/METRICS_CATALOG.md)** — 10 metrics as
metric → why it matters → how to get it. Also verified today: `fossilize-disasm --target isa`
works and emits NIR + ACO IR + Final Assembly with `s_delay_alu` operands decoded
(142 of them in one sampled shader) — this closes PLAN.md §8 risk 2.

## Apresentação para o orientador

`Apresentacao.drawio` (PT-BR) ganhou 15 caixas novas — nada do texto original foi tocado
(45 células preservadas, zero sobreposição). Backup: `Apresentacao.drawio.backup-*`.
Amarelo = correção · Verde = dado medido · Azul = método · Vermelho = risco.
Correções principais: é **SPIR-V**, não RISC-V; tirar o scoreboard custa **performance, não
estabilidade** (não deveria crashar); a bancada é **7800 XT / gfx1101**, não a 7900 XTX;
Fossilize grava *criação* de pipeline e o replay **recompila, não executa**.

## Where we stopped

- **Metric 2 proven** on Metro EE (session `20260724-101611`): 52.8 fps avg, 1%/0.1% low
  37.4/34.3, 5810 frames/110 s, 281 MB foz captured. Whole armed-launch chain works in Proton.
- **Pause-frame parser fix**: `autostart_log=1` logs menus as multi-minute "frames"; >200 ms
  now dropped and counted.
- **Metric 3 verified feasible**: foz carries SPIR-V + layouts (only 15–19 layouts cover 100k+
  pipelines); `libfossilize.a` already built, so the harness reads create-infos from the
  replayer API. Only new code is the executor (~850 lines C++). Hazards: raw GPU pointers
  (arena + pattern fill) and bindless indexing (robustness2). See SHADERBENCH_PLAN.md.
- **Repetition policy set**: L1 median of 200 → L2 drop-worst-of-4 mean → L3 interleave A/B.

## Repo state after the 2026-07-28 cleanup

```
src/
├── cli.py                 entry point (`tcc`)
├── core/                  config, paths, session, provenance, util, toolchain, schemas/
├── shader_extractor/      foz.py — capture/snapshot/delta/extract  (+ corpus.py, SB-1)
├── analysis/              stats.py, mine.py                        (+ compare.py, isa.py)
├── benchmark/             game_bench.py                            (+ shaderbench.py, ledger.py)
└── launcher/              arm.py, steam.py
```

- `src/tcc/` removed → top-level packages; `_attic/`, `.github/modernize/`, `reports/`,
  `networkx` all deleted. Recover attic formulas: `git show a7f0d75:_attic/prototypes/triage.py`.
- Fixed while moving: `tcc doctor` globbed only `steam_root`, hiding every game on another drive.

## Next step

**SB-0 spike `[GPU]`** — the one experiment that can invalidate Metric 3, so it comes first.
Minimal `StateCreatorInterface` over a single-pipeline pruned foz: create one Remnant II
compute pipeline, arena + BDA pattern fill, one dummy descriptor set, dispatch, timestamp.

- **Expect:** same shader timed twice within 2%, **no GPU fault**. Also settles whether a
  colon-separated `VK_ICD_FILENAMES` exposes both RADV builds in one process (→ true
  interleaving) or whether we fall back to process-level alternation.
- **Why first:** if a DXIL-translated shader can't run standalone without hanging the queue,
  Metric 3 doesn't exist. Better to know from a 200-line spike than a 850-line harness.
- Run it in a separate process with a watchdog so a queue loss doesn't take the session.

**Also pending your decision:**
1. **Delete the original shadercaches?** Everything is copied and sha256-verified; deleting
   frees ~28.8 GB across your drives. Games recompile shaders on next launch (one-time stutter).
2. **Run the null A/B across the full 22.95 GB corpus?** ~1–6 h per driver, background job.
   Remnant II alone already proved the chain, so this is for coverage, not validation.

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

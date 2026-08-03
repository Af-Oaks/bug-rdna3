# ONGOING — live checkup

Summary of the last few sessions. **Where we are, what runs next, what to expect.**
Details live in the linked docs — this file stays short on purpose.

- **Updated:** 2026-08-03 · **Branch:** `rework` · nothing committed since `281472b`
- **Details:** [TODO.md](TODO.md) (phases) · [docs/METRICS_PLAN.md](docs/METRICS_PLAN.md)
  (Metrics 1+2) · [docs/SHADERBENCH_PLAN.md](docs/SHADERBENCH_PLAN.md) (Metric 3, corpus, ledger)
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

## 2026-08-03 — corpus merge, then the heavy cleanup

Plan: **[docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md)**. Mechanism moved into
**[DOMAIN.md](DOMAIN.md)**; rules rewritten in **[REPOCONTEXT.md](REPOCONTEXT.md)**.
`CODE_AUDIT.md` and `PIPELINE.md` were folded into those plus the per-folder
`CONTEXT.md` files, and deleted.

**Coverage — the correction that reordered everything.** Analysing one
arbitrarily-chosen `.foz` ignored **52% of re6, 50% of remnant2, 42% of
helldivers2**. `tcc corpus build` merges them all; Fossilize is content-addressed
so a merge is a **union** (remnant2 5,035 + 5,038 → 5,038). Gains:
**cyberpunk2077 +21.0%** (19,316 → 23,365), **kh3 +19.5%** (83,283 → 99,493).
The `run_recorded`/`steam_precache` split is indexed *before* the merge and
rejoined as a `provenance` column (kh3: 83,288 / 16,205 preserved).

**Provenance backbone reconnected.** `run_recorded()` was written and called by
nothing. Now `replay_stats` and `disasm` go through it — and a bug it existed to
prevent was found by checking: `env_snapshot()` read the *parent's* `os.environ`,
so every snapshot came out `{}`. It now snapshots the child's env. A manifest
finally records `VK_ICD_FILENAMES=…/build/install_custom/…`, `RADV_DEBUG=nocache`,
the isolated cache dir, and which `fossilize-*` binary resolved.

**Deleted:** 15 stub subcommands (~98 lines — `--help` advertised six command
groups that all exit 2), `paths.steam_root()`, `config.list_profiles()`,
`armed_profile.schema.json` (described a payload nothing produced), the
`armed_profile` and `top_n_offenders` config keys, a dead `cfg` parameter, the
duplicated foz-filename flattener, the duplicated foz-selection heuristic, the
hand-rolled logging in `stats.py`, `.get()` defaults defending against a
schema-forbidden manifest version, and an unreachable `None` branch.

**Fixed:** `subgroup_size` promoted · `vopd_ratio` replaces raw `vopd` ·
`mine` groups by `(driver, stage)` · collapsed rows reported · one `TccError`
base · schema loading cached · `collect` re-run no longer hashes 22.95 GB to
decide it has nothing to do · `bench summarize` scoped to the current run ·
`snapshot()` now **asserts** the invariant `run_created` depends on.

**Dry run green:** 16 modules import, all files compile, 13 CLI surfaces ok,
errors print `error:` not tracebacks, null A/B still **IDENTICAL** (17,725 rows,
19 metrics, zero deltas, 11 collapsed each side).

⚠️ **10 of 18 games still hold unsaved shader data** — `tcc collect --check`
before uninstalling anything (re6 is missing 256 of 259 files).

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

Layout and per-package intent now live in **[src/CONTEXT.md](src/CONTEXT.md)** and the
six folder files it links. Attic formulas: `git show a7f0d75:_attic/prototypes/triage.py`.

## Next step

**Agreed order (your call, 2026-08-03):** ✅ collection safety → dynamic offender
chart → audit cleanup pass → `isa.py` + crash safety.

1. **`run_recorded()` wiring (A1)** — biggest open defect: no stats table records which
   ICD produced it. Do it before the next stats run, since it changes what gets recorded.
2. **Dynamic offender chart** — self-contained HTML over
   `20260803-185951_remnant2_corpus-verify` (17,736 rows, post-promotion, has
   `subgroup_size` + `provenance`): live z-scores, adjustable weights, methodology on
   the chart. Should still parse `extra` so older tables load.
3. **`isa.py`** — parse Final Assembly, count instruction classes, diff A vs B, feed the
   ledger. State plainly: static counts show what changed in the code, **not** its
   execution cost. That needs Metric 3 or SQTT.
4. **SB-0 spike `[GPU]`** — the experiment that can invalidate Metric 3. One compute
   pipeline, arena + BDA fill, dispatch, timestamp. Expect the same shader timed twice
   within 2% and no GPU fault. Separate process + watchdog so a queue loss cannot take
   the session.

~~**Delete the original shadercaches?**~~ **NOT SAFE — `tcc collect --check` says 10 of
18 games hold uncollected data** (re6 is missing 256 of 259 files). Run
`tcc collect` on the listed games first, re-check, *then* reclaim the ~28.8 GB.

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

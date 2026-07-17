# TODO — Repo Rework Status & Remaining Work

Work paused mid-rework on 2026-07-16. Branch: **`rework`**. The full approved plan is in
[docs/PLAN.md](docs/PLAN.md) — read it before resuming. This file tracks what is DONE vs LEFT.

## Where things stand

| Phase | Status | Evidence |
|---|---|---|
| 0 — Restructure | ✅ committed `d609d60` | old pipeline in `_attic/`, gfxreconstruct + RGA source deleted (2.4GB freed), data blobs in `data/archive/` |
| 1 — Core package | ✅ committed `acbfa86` | `pip install -e .` works; `tcc doctor`, `tcc session new/list/show/note/close` verified |
| 2 — Foz + stats engine | 🟡 **WIP, committed as WIP** | `foz.py`/`stats.py`/`mine.py` written; real GPU stats run SUCCEEDED (see below); agent was interrupted mid-"re-run with fix" |
| 3 — Arm/launch wrapper | ❌ not started | |
| 4 — ISA/compare/RGA | ❌ not started | |
| 5 — Shaderlab + C++ harness | ❌ not started | |
| 6 — Bench + capture | ❌ not started | |
| 7 — Reports + docs rewrite | ❌ not started | `docs/THESIS_NOTES.md` exists; README/AGENTS still describe the OLD layout |

## Key result already in hand (Phase 2 partial)

`fossilize-replay --enable-pipeline-stats` ran against `data/foz/remnant2/steamapp_pipeline_cache.foz`
under the **stock local Mesa build** on the 7800 XT and produced
`data/sessions/remnant2/20260716-214415_remnant2_sample-mining/stats/stats.stock.csv`
(**17,730 rows**, tidy format) + `_raw.stock.csv` (raw fossilize CSV).

**The raw stats format is now known** (document assumed unknown in plan §8 risk 1 — resolved).
Raw CSV columns include per-stage:
`SGPRs, VGPRs, Spilled SGPRs/VGPRs, Code size, LDS size, Scratch size, Subgroups per SIMD (=max waves),`
and ACO extras: `Instructions, Copies, Branches, Latency, Inverse Throughput, VMEM/SMEM Clause,`
`Pre-Sched SGPRs/VGPRs, VALU, SALU, VMEM, SMEM, VOPD`.
→ **VOPD counts and instruction mix come straight from the driver** — much of the thesis analysis
does not even need ISA parsing. The tidy parser keeps unknown stats in the `extra` JSON column.

## To resume (next session)

1. `git checkout rework` — inspect the WIP commit for Phase 2 state.
2. **Finish Phase 2**: the agent was re-running stats after a parser fix when stopped.
   Verify `stats.stock.csv` is coherent, then finish per plan §7 acceptance:
   - `tcc mine --session @last --top 10` → ranked offenders table + `offenders.csv`
     (consider adding `VOPD`, `VALU`, `Latency` from `extra` into the score — they're free now).
   - Smoke-test `fossilize-disasm --target isa` on the #1 offender hash (verify it accepts a
     `.foz` positional; plan §8 risk 2 still unverified).
   - `tcc foz snapshot/delta/extract` end-to-end still untested (needs a real game run or a
     synthetic before/after pair).
   - Commit as "Phase 2: foz + stats engine".
3. **Phase 3** (plan §4/§5): `arm.py`, `steam.py`, `bin/tcc-launch.sh`. Acceptance via vkcube
   (`tcc arm --profile custom && bin/tcc-launch.sh vkcube` must show the custom ICD + one-shot
   consumed; stale/absent profile must launch untouched). Then **[HUMAN]** set Steam launch
   options once per game: `<repo>/bin/tcc-launch.sh %command%`.
4. **Phase 4**: `isa.py` (port stall_ratio/vopd_ratio from `_attic/prototypes/triage.py`),
   `hazards.py` port, `compare.py`, `rga.py`, `tcc mesa build`. Sanity check: stock-vs-custom
   compare must show ZERO deltas (custom ACO layer is still unmodified).
5. **Phase 5**: `shaderlab/harness/main.cpp` (~400-line Vulkan compute dispatch harness,
   spec in plan §5), `lab.py`, experiments `000_smoke` + `001_vopd_saturation`.
6. **Phase 6**: `bench.py` (mangohud CSV), `renderdoc_ctl.py` (backend A: python target-control;
   backend B: hotkey + `--collect-only`). Needs human installs first (below).
7. **Phase 7**: `report.py`, rewrite README.md/AGENTS.md for the new layout, write
   docs/SETUP.md, docs/WORKFLOWS.md, docs/GAMES.md.

## Human-only tasks (can be done anytime, unblock Phases 3/6)

- [ ] `sudo apt install mangohud renderdoc vkmark` (check whether Ubuntu's renderdoc ships the
      python module; if not, get the tarball from renderdoc.org)
- [ ] Download AMD prebuilt **RGA** Linux tarball → unpack to `tools/rga/` (record version in docs/SETUP.md)
- [ ] Download **GravityMark** → `tools/gravitymark/`; fill `launch_args` in `config/games/gravitymark.toml`
- [ ] Steam launch options (once per game): `/home/methos/Documents/faculdade/TCC_bug_amd/bin/tcc-launch.sh %command%` (after Phase 3 exists)
- [ ] **Clear the old broken GFXRECON launch options from Remnant II properties** (if still set)
- [ ] Install games: Cyberpunk 2077, Shadow of the Tomb Raider, Black Myth: Wukong **Benchmark Tool (appid 3132990)**, FFXV Windows Benchmark (non-Steam), Control
- [ ] Confirm `_attic/` contents can eventually be deleted once tcc reaches parity (no rush)

## Standing facts (verified, do not re-derive)

- GPU: RX 7800 XT = Navi 32 = **gfx1101** (old docs saying gfx1100 are wrong).
- Fossilize CLIs live in `build/install/bin/`; stock Mesa = `build/install`, custom = `build/install_custom`
  (custom ACO overlay `custom_mesa_layer/` is **still byte-identical to stock** — no compiler mods yet).
- Steam foz caches: `~/.local/share/Steam/steamapps/shadercache/<appid>/fozpipelinesv6/steamapprun_pipeline_cache.*` (no `.foz` extension).
- Armed-profile file must live under `$HOME` (`~/.tcc/`) — Pressure Vessel does not reliably expose `/tmp`.
- The venv is `build/venv`; the CLI is `./build/venv/bin/tcc`.

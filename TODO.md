# TODO — Repo Rework Status & Remaining Work

Work paused mid-rework on 2026-07-16. Branch: **`rework`**. The full approved plan is in
DOMAIN.md — read it before resuming. This file tracks what is DONE vs LEFT.

**Live context:** [ONGOING.md](ONGOING.md) — read that first; it holds the current position,
the next command, and what result is expected.

**All three metrics are built** (2026-08-03). The mechanism is [DOMAIN.md](DOMAIN.md);
this file is the queue of what is left.

- **Metric 1 (static)** — `tcc stats run` / `mine` / `compare` / `isa`. Null A/B passes.
- **Metric 2 (frame rate)** — `tcc bench run`, validated on Metro EE.
- **Metric 3 (shaderbench)** — `tcc bench shaders`. SB-0 ran and set a scope
  limit: **native-Vulkan titles only**; vkd3d/DX12 shaders fault when isolated
  (0 of 8 on Remnant II). Null A/B on mechabellum: median −0.008%.
- **Ledger** — `tcc ledger add/show`, joining all three.

## Where things stand

| Phase | Status | Evidence |
|---|---|---|
| 0 — Restructure | ✅ committed `d609d60` | old pipeline in `_attic/`, gfxreconstruct + RGA source deleted (2.4GB freed), data blobs in `data/archive/` |
| 1 — Core package | ✅ committed `acbfa86` | `pip install -e .` works; `tcc doctor`, `tcc session new/list/show/note/close` verified |
| 2 — Foz + stats engine | 🟡 **WIP, committed as WIP** | `foz.py`/`stats.py`/`mine.py` written; real GPU stats run SUCCEEDED (see below); agent was interrupted mid-"re-run with fix" |
| 3 — Arm/launch wrapper | ✅ done 2026-07-23 | `arm.py`/`steam.py`/`bin/tcc-launch.sh`; vkcube acceptance passed (stock ICD `Mesa 26.1.0-devel` applied + one-shot consumed; unarmed/stale/wrong-appid all launch untouched; exe-override substitution verified) |
| 4 — ISA/compare/RGA | ❌ not started | |
| 5 — Shaderlab + C++ harness | ❌ not started | |
| 6 — Bench + capture | 🟡 bench slice done 2026-07-23 | `bench.py`: `tcc bench run` orchestrator (session→foz before→arm→launch→wait→foz after/delta→CSV summary) + `tcc bench summarize` (MangoHud parser validated on synthetic data). renderdoc_ctl.py still pending; mangohud still not installed |
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
3. ~~**Phase 3**~~ DONE 2026-07-23 (see table above). Remaining human step: set Steam launch
   options once per game: `<repo>/bin/tcc-launch.sh %command%`. First real-game run should be
   **Control** (installed + real foz cache verified):
   `tcc bench run --game control --profile bench-mangohud` (after mangohud is installed).
4. **Phase 4**: `isa.py` (port stall_ratio/vopd_ratio from `_attic/prototypes/triage.py`),
   `hazards.py` port, `compare.py`, `rga.py`, `tcc mesa build`. Sanity check: stock-vs-custom
   compare must show ZERO deltas (custom ACO layer is still unmodified).
5. **Phase 5**: `shaderlab/harness/main.cpp` (~400-line Vulkan compute dispatch harness,
   spec in plan §5), `lab.py`, experiments `000_smoke` + `001_vopd_saturation`.
6. **Phase 6**: `bench.py` (mangohud CSV), `renderdoc_ctl.py` (backend A: python target-control;
   backend B: hotkey + `--collect-only`). Needs human installs first (below).
7. **Phase 7**: `report.py`, rewrite README.md/AGENTS.md for the new layout, write
   docs/SETUP.md, docs/WORKFLOWS.md, docs/GAMES.md.

## Human-only tasks (can be done anytime, unblock Phase 6)

- [x] mangohud — installed 2026-07-23; full capture chain verified (vkcube through the wrapper:
      stock ICD + autostart MangoHud CSV + `tcc bench summarize`, 1503 frames parsed clean).
      NOTE: the "driver" column in MangoHud CSV metadata is the system **OpenGL** driver
      (a local Mesa 25.3.0-devel GL stack), NOT the Vulkan ICD in use — the ICD of record is
      in the session launch log / env snapshot.
- [ ] `sudo apt install renderdoc vkmark` (check whether Ubuntu's renderdoc ships the
      python module; if not, get the tarball from renderdoc.org)
- [ ] **Steam launch options, once per game** (Properties → Launch Options):
      `/home/methos/Documents/faculdade/TCC_bug_amd/bin/tcc-launch.sh %command%`
      → set for: control, cs2, re-requiem, remnant2 (+ metro-ee / marvelrivals when downloaded)
- [ ] **CS2**: subscribe to workshop map **3240880604** ("CS2 FPS BENCHMARK DUST2") once
- [ ] **Metro EE** (after download finishes): find `Benchmark.exe` in the install dir, record the
      path in `config/games/metro-ee.toml` instructions; launch it via
      `tcc arm ... --exe-override <path>/Benchmark.exe` (wrapper substitutes it for MetroExodus.exe)
- [ ] Download AMD prebuilt **RGA** Linux tarball → unpack to `tools/rga/` (record version in docs/SETUP.md)
- [ ] Download **GravityMark** → `tools/gravitymark/`; fill `launch_args` in `config/games/gravitymark.toml`
- [ ] **Clear the old broken GFXRECON launch options from Remnant II properties** (if still set)
- [ ] Finish downloads: Metro Exodus EE (1449560), Marvel Rivals (2767030); wukong **Benchmark Tool
      (appid 3132990)** not installed yet (base game 2358720 is)
- [ ] Confirm `_attic/` contents can eventually be deleted once tcc reaches parity (no rush)

## Game matrix status (2026-07-23, verified from local appmanifests)

| slug | appid | state | benchmark path |
|---|---|---|---|
| control | 870780 | ✅ installed (SataSSD) | manual scene; foz snapshot already tested against its real 12MB cache |
| cs2 | 730 | ✅ installed (China Democracy1) | workshop map 3240880604, prints avg/1% lows to console |
| re-requiem | 3764200 | ✅ installed (SataSSD) | NO builtin bench → manual scenes (leon_intro / first_street) |
| metro-ee | 1449560 | ⏳ downloading (4%) | standalone Benchmark.exe via wrapper exe-override |
| marvelrivals | 2767030 | ⏳ downloading (1%) | NO builtin bench → practice range only (anti-cheat: never capture online) |
| remnant2 | 1282100 | ✅ installed (main lib) | manual scenes; legacy foz layout (hex dir) handled |

**Shadercache gotchas discovered:** caches live in the game's OWN library folder (not
`~/.local/share/Steam`) — `steam.library_folders()` parses libraryfolders.vdf and
`foz.snapshot` now searches all of them. New Steam layout is
`fozpipelinesv6/steam_pipeline_cache.foz` (WITH extension, contradicting the old gotcha);
legacy is `steamapprun_pipeline_cache.<hex>/steamapp_pipeline_cache.foz`. The game TOML glob
`**/*pipeline_cache*` (files only) matches both and deliberately excludes `replay_cache.*`.

## New direction (what this refactor changes)

The rework is not just a cleanup — it changes the method:

1. **Framing**: from "prove RDNA3 has a hardware flaw" → "measure which workload/pipeline/compiler
   characteristics correlate with high vs low gen-over-gen gains". Hypotheses (s_delay_alu hazard
   offloading, VOPD underuse, VGPR/occupancy pressure) become measurable correlations.
2. **Stats-first instead of log-parsing**: the old path was a 2.1GB `RADV_DEBUG=shaders` dump parsed
   by regex. The new path asks the driver directly — `fossilize-replay --enable-pipeline-stats`
   (VK_KHR_pipeline_executable_properties) yields per-stage VGPRs/waves/**VOPD/VALU/SALU/latency**
   keyed by exact pipeline hash. ISA text is extracted only for top-N offenders via
   `fossilize-disasm --target isa --filter-*`. Kilobytes instead of gigabytes.
3. **Armed-profile launches instead of editing Steam by hand**: Steam launch options get set ONCE
   per game to `bin/tcc-launch.sh %command%`; every experiment after that is `tcc arm --profile X`
   → launch. Profiles swap driver ICD (stock/custom ACO), RADV flags, capture layers, mangohud.
4. **Benchmark-first game matrix**: Tier 0 synthetics (vkmark/vkpeak/GravityMark — fully scriptable,
   no gameplay), Tier 1 built-in benchmarks (Cyberpunk, SOTTR, Wukong bench tool, FFXV bench),
   Tier 2 manual scenes (Remnant II, Control) only where no benchmark exists.
5. **Shaderlab for causality**: real games show correlations; the C++ dispatch harness + authored
   GLSL experiments isolate single variables (VOPD on/off, dependency chains) for cause-and-effect.
6. **One CLI (`tcc`), one session model**: every artifact traceable by session id + sha256, replacing
   three loosely-coupled track scripts. Old Track C hash-token correlation is obsolete — the stats
   flow is exact-hash end-to-end.

## Gotchas / lessons learned (do not repeat these)

- **Never inject native Linux Vulkan layers into Proton by hand.** The GFXReconstruct saga failed on
  three stacked walls: Steam's 32-bit pre-loader can't load a 64-bit layer (ELF panic), VKD3D-Proton's
  allocator collides with page-fault memory tracking, and Pressure Vessel blocks unmounted paths.
  The final "fix" even pointed at a LunarG SDK dir that was never extracted. Use Valve-integrated
  paths instead: `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` (Steam ships correctly-paired layers in-container).
- **gfx1100 ≠ gfx1101.** The 7800 XT (Navi 32) is **gfx1101**; gfx1100 is Navi 31 (7900 XT/XTX).
  Early notes/RGA targets used gfx1100 — any occupancy numbers from that target are for the wrong chip.
- **Check that a tool is actually built before planning around it.** 1.5GB of RGA source sat unbuilt
  for months; the `rga` "binary" was a 1.3KB bash wrapper and amdllpc a git-lfs pointer stub.
  Prefer AMD's prebuilt release tarballs.
- **Don't parse what the driver will tell you.** The 2GB log + OOM + streaming-parser saga was
  unnecessary: `--enable-pipeline-stats` existed all along, and ACO even reports VOPD counts per stage.
- **Fossilize records at pipeline *creation*, not draw time.** UE5 precreates PSOs at load screens,
  so a foz before/after delta means "created during the window", NOT "drawn in the scene". The
  RenderDoc frame capture is the ground truth for what was actually on screen; keep both.
- **Steam foz files have no `.foz` extension** (`steamapprun_pipeline_cache.<hex>`) — never glob `*.foz`.
- **Steam launch options have no API.** The one-time `%command%` wrapper + `~/.tcc/armed.env` file is
  the only sane automation path. The armed file must live under `$HOME` — Pressure Vessel does not
  reliably share `/tmp`. The wrapper must NEVER break a launch (every failure → `exec "$@"`).
- **Verify appids, don't trust memory**: the Wukong *Benchmark Tool* is 3132990; 2358720 is the base game.
- **The custom ACO is still stock.** `custom_mesa_layer/` has zero modifications, so
  stock-vs-custom must diff to zero — that's the Phase 4 sanity check, not a disappointment.
- **The git repo was never the bloat problem** — 20MB of history vs ~7GB of untracked working-tree
  junk. Cleanup = disk hygiene, not git surgery.

## Standing facts (verified, do not re-derive)

- GPU: RX 7800 XT = Navi 32 = **gfx1101** (old docs saying gfx1100 are wrong).
- Fossilize CLIs live in `build/install/bin/`; stock Mesa = `build/install`, custom = `build/install_custom`
  (custom ACO overlay `custom_mesa_layer/` is **still byte-identical to stock** — no compiler mods yet).
- Steam foz caches: `~/.local/share/Steam/steamapps/shadercache/<appid>/fozpipelinesv6/steamapprun_pipeline_cache.*` (no `.foz` extension).
- Armed-profile file must live under `$HOME` (`~/.tcc/`) — Pressure Vessel does not reliably expose `/tmp`.
- The venv is `build/venv`; the CLI is `./build/venv/bin/tcc`.

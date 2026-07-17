# TCC Repo Rework — Full Plan (greenfield `tcc` package + automated capture/bench/shaderlab)

## Context

This thesis repo (RDNA3 gain-variability investigation on RX 7800 XT / gfx1101, Linux + Steam/Proton + Mesa RADV/ACO) has a solid session/manifest concept but suffers from: manual "dark fumbling" capture chores (.foz snapshots, Steam launch options edited by hand), a 2.1GB-log-parsing analysis path, 2.4GB of dead vendored trees (gfxreconstruct — abandoned approach; radeon_gpu_analyzer — never built), prototype scripts scattered at the root, and no way to author/measure custom shaders.

User decisions (asked and answered):
- **Cleanup**: Full clean — delete `gfxreconstruct/` and `radeon_gpu_analyzer/` source; archive big data blobs.
- **Pipeline**: Greenfield rewrite — new unified `tcc` Python package + single CLI; old code parked in `_attic/`.
- **Shader workbench**: includes a C++ Vulkan compute dispatch harness (real GPU timings).
- **Game matrix**: Cyberpunk 2077, Shadow of the Tomb Raider, Black Myth: Wukong Benchmark Tool (free standalone), FFXV Windows Benchmark (free standalone, Proton), Control (manual-scene), Remnant II (installed, manual-scene), plus Tier-0 synthetics (vkmark, vkpeak, GravityMark).

Verified facts the plan relies on:
- Git history is tiny (20MB, 132 tracked files); all bulk is untracked. Tracked: `custom_mesa_layer/` (ACO overlay, currently unmodified), `scripts/`, `analysis/`, `src/{hazards,triage}.py`, `extract.py`, `todo`, docs.
- `build/install/bin/` has all Fossilize CLIs. **Key flags (verified via --help)**: `fossilize-replay --enable-pipeline-stats <path>` (VK_KHR_pipeline_executable_properties per-pipeline stats), `--pipeline-hash`, `--*-pipeline-range`, `--timeout-seconds`, `--num-threads`; `fossilize-prune --whitelist/--filter-*` (scene-scoped sub-DBs); `fossilize-disasm --target asm|glsl|isa --filter-* --output`; `fossilize-list --tag N --size --connectivity`.
- Both Mesa builds exist: `build/install` (stock) and `build/install_custom` (custom ACO via `custom_mesa_layer/` rsync overlay — currently byte-identical to stock).
- On PATH: glslangValidator, spirv-dis/as, steam, vkcube, vulkaninfo, gamemoderun. MISSING: renderdoc, mangohud, amdgpu_top, rga (needs prebuilt AMD tarball).
- Remnant II foz cache: `~/.local/share/Steam/steamapps/shadercache/1282100/fozpipelinesv6/steamapprun_pipeline_cache.*` (no .foz extension). Sample foz in repo: `src/shaders/remnant2/steamapp_pipeline_cache.foz` (129MB).
- Steam launch options can't be set programmatically → one-time manual `%command%` wrapper setup per game, then everything flows through an "armed profile" file.
- GPU: RX 7800 XT (RADV NAVI32), system Mesa 25.2.8, Vulkan 1.4.

---

## 1. Target repo tree

```
TCC_bug_amd/
├── README.md / AGENTS.md / DOMAIN.md      # rewritten/updated for new layout
├── pyproject.toml                         # package `tcc`, console script `tcc`, deps: pandas, networkx, jsonschema
├── .gitignore                             # rewritten: data/, tools/, lib/, build/, pdf_context/, __pycache__/, *.pyc, .tcc/
├── config/
│   ├── tcc.toml                           # global paths/defaults (see §2)
│   ├── games/*.toml                       # cyberpunk2077, sottr, wukong-bench, ffxv-bench, control, remnant2, vkmark, vkpeak, gravitymark
│   └── profiles/*.toml                    # baseline, stock, custom, stock-novopd, capture-rdc, capture-sqtt, bench-mangohud
├── src/tcc/                               # the package (all new code; modules in §3)
│   └── schemas/*.schema.json              # session_manifest, artifact_registry, armed_profile, stats_table
├── bin/tcc-launch.sh                      # Steam %command% wrapper (POSIX sh, "never break a launch")
├── shaderlab/
│   ├── harness/{main.cpp, Makefile, README.md}   # Vulkan compute dispatch harness (~400 lines)
│   └── experiments/{000_smoke, 001_vopd_saturation}/{shader.comp, experiment.toml}
├── scripts/{setup_env.sh, build_custom_aco.sh}   # only build scripts remain
├── custom_mesa_layer/                     # unchanged (tracked ACO overlay)
├── docs/{SETUP.md, WORKFLOWS.md, GAMES.md, THESIS_NOTES.md, scenes/*.md}
├── reports/                               # tracked generated summaries
├── _attic/                                # frozen old code: analysis_pipeline/, analysis/, prototypes/{extract,triage,hazards}.py, shell/{gpu_test_runner,test_fossilize}.sh, README.md
├── data/                                  # GITIGNORED: sessions/, foz/<game>/, shaderlab/, archive/ (raw_dump.log 2.1GB, rdna3_pipeline_samples.json 280MB)
├── tools/                                 # GITIGNORED: rga/ (prebuilt tarball), gravitymark/
└── lib/, build/, pdf_context/             # GITIGNORED, unchanged
```

Deleted outright: `gfxreconstruct/` (934MB), `radeon_gpu_analyzer/` (1.5GB), `isa_dumps/` (after move), `logs/` (empty), root `__pycache__/`, `src/` (after moves), old `analysis/` (after attic move), `todo` (absorbed into docs/THESIS_NOTES.md).

## 2. Config formats

**`config/tcc.toml`**: `[paths]` data_dir, mesa_stock=`build/install`, mesa_custom=`build/install_custom`, tools_dir, steam_root=`~/.local/share/Steam`, armed_profile=`~/.tcc/armed.json` (MUST be under $HOME — pressure-vessel mounts $HOME; /tmp is unsafe), wrapper=`bin/tcc-launch.sh`. `[defaults]` gpu_arch=`gfx1101`, replay_threads, replay_timeout_s, top_n_offenders=25.

**`config/games/<slug>.toml`**: `[game]` slug, name, kind (steam|non-steam-proton|native-cli), appid, runtime, api (vulkan|vkd3d|dxvk), engine, cohort (high-gain|low-gain|synthetic|reference). `[benchmark]` type (builtin|standalone|manual-scene|cli), trigger (menu|autostart|cli-args), launch_args, duration_hint_s, instructions. `[foz]` cache_glob (`steamapps/shadercache/{appid}/fozpipelinesv6/steamapprun_pipeline_cache.*`). `[[scenes]]` id, kind (benchmark|manual), protocol_doc.

Matrix: cyberpunk2077 (1091500, vkd3d, builtin/menu, high-gain), sottr (750920, native vulkan, builtin/menu, reference), wukong-bench (free standalone Steam benchmark tool — **verify appid from Steam store at implementation time**, UE5/vkd3d, high-gain), ffxv-bench (non-steam-proton, exe_path config, standalone), control (870780, manual-scene), remnant2 (1282100, UE5/vkd3d, manual-scene, installed), vkmark/vkpeak/gravitymark (native-cli, fully automated, synthetic).

**`config/profiles/<name>.toml`**: `[profile]` name, driver (system|stock|custom), radv_debug[], radv_perftest[], mangohud, renderdoc, sqtt, shader_cache_dir ("session"=isolated MESA_SHADER_CACHE_DIR|"default"); `[env]` free-form extras.

**Session dir** `data/sessions/<game>/<session_id>/` (id = `YYYYMMDD-HHMMSS_<game>_<scene>`): `session.json` (manifest: schema_version 2, game, scene, status, profiles_used, tool_resolution, steps[], notes[]), `artifacts.json` (registry: path, sha256, kind, producer, timestamp, confidence — defaults "exact" since hashes are exact end-to-end; strong/weak/unresolved kept only for manual annotations), `logs/`, `foz/` (before/, after/, delta.json, scene.foz), `stats/`, `isa/<driver>/`, `isa_metrics/`, `captures/`, `bench/`, `reports/`.

## 3. `tcc` package modules

- **`paths.py`** — canonical path resolution (repo root walk-up, data dir, session root, steam root, armed profile path).
- **`config.py`** — TOML loading (stdlib tomllib) + validation; `resolve_icd(driver)`; **`profile_env(profile, session) -> dict`** — THE single place env is computed (VK_ICD_FILENAMES, RADV_DEBUG, RADV_PERFTEST, MESA_SHADER_CACHE_DIR, ENABLE_VULKAN_RENDERDOC_CAPTURE…). All A/B-sensitive invocations force `nocache` + isolated shader cache here.
- **`session.py`** — create/load/list; `Session.record_step`, `.record_artifact` (sha256), `.save()`. Session ref accepts full id, unique substring, or `@last`.
- **`provenance.py`** — sha256, env snapshots, `run_recorded(session, step, argv, env)` subprocess wrapper that tees to logs/ and appends to steps[].
- **`toolchain.py`** — resolution order `build/install/bin` → `tools/**` → PATH; `doctor()` returns checks with remedies (tools, ICD jsons exist, ~/.tcc writable, wrapper executable, per-game foz caches, RGA supports gfx1101).
- **`steam.py`** — `shadercache_foz(game)` glob; `launch(game)` (`steam -applaunch <appid>` | direct exec | documented manual for non-steam-proton); best-effort `wait_for_exit`.
- **`arm.py`** — writes BOTH `~/.tcc/armed.json` (canonical) and `~/.tcc/armed.env` (flat KEY=value + TCC_APPID, TCC_ONE_SHOT, TCC_EXPIRES_EPOCH, TCC_LOG_DIR, TCC_MANGOHUD) so the wrapper needs zero JSON parsing. One-shot by default, TTL default 240 min.
- **`foz.py`** — snapshot (copy matched shadercache files into session), `list_hashes` (fossilize-list), `delta` (after−before per tag → delta.json), `extract` (fossilize-prune --whitelist → scene.foz), `disasm(foz, hash, target, env)` (**runs the real driver — must receive profile env; ICD choice decides stock vs custom ISA**), `replay_stats(foz, out, env)` (fossilize-replay --enable-pipeline-stats).
- **`stats.py`** — run + parse pipeline-stats into tidy pandas rows (pipeline_hash, stage, driver, vgprs, sgprs, spills, code_size, lds, scratch, max_waves…). **Parser must be name-substring-tolerant and keep unmatched stats in an `extra` column** — exact stat names are fixed after the first real run (Phase 2 step 1).
- **`isa.py`** — absorbs triage.py: per-ISA-file `total_instructions`, `s_delay_alu_count`, `s_waitcnt_count` (incl. RDNA3 `s_wait_*` forms), `s_nop_count`, `v_dual_count`; derived **`stall_ratio` and `vopd_ratio` exactly as in `_attic/prototypes/triage.py`** (names appear in the thesis).
- **`hazards.py`** — port of `src/hazards.py` (networkx RAW-dep DAG → theoretical stall cycles); used by `tcc isa metrics --deep`.
- **`rga.py`** — prebuilt RGA (`tools/rga/`) vk-offline for gfx1101: ISA + live-VGPR + occupancy; degrades gracefully if absent.
- **`mine.py`** — offender ranking: `score = z(vgprs) + z(-max_waves) + z(code_size) + 3*z(spilled_vgprs)`; writes stats/offenders.csv.
- **`compare.py`** — A/B join on (pipeline_hash, stage) with delta columns; `isa_diff(hash, a, b)` unified diff.
- **`bench.py`** — mangohud env construction (`MANGOHUD_CONFIG=output_folder=<session>/bench,no_display,...`), CSV parsing (avg fps, 1%/0.1% lows, frametime percentiles), bench_summary.json.
- **`renderdoc_ctl.py`** — Backend A (opportunistic): python `renderdoc` module target-control — connect to live injected app, TriggerCapture at frame/delay, copy .rdc. Backend B (guaranteed): operator presses F12; `--collect-only` scans known capture dirs for .rdc newer than session start and registers newest.
- **`lab.py`** — shaderlab orchestration (§5).
- **`report.py`** — session + cohort markdown.
- **`cli.py`** — argparse subparsers; handlers ≤20 lines delegating to modules; global `--json`.

## 4. CLI surface

```
tcc doctor [--json]
tcc session new --game SLUG --scene SCENE [--note TEXT] | list | show | note | close
tcc arm --session S --profile NAME [--ttl MIN=240] [--sticky] | arm show | disarm
tcc launch --session S [--wait] [--args "..."]
tcc foz snapshot --session S --label {before,after} | delta | extract [--hashes FILE] | import --game SLUG PATH
tcc stats run --session S --driver {system,stock,custom} [--foz PATH] | show [--sort col] [--top N]
tcc mine --session S [--driver D] [--top N=25] [--rank waves|vgprs|spill|code_size|score]
tcc isa extract --session S --driver D (--hash H... | --top N) | metrics [--deep] | diff --hash H --a stock --b custom
tcc rga run --session S (--hash H | --top N)
tcc compare --session S --a stock --b custom [--llvm] [--out MD]
tcc capture rdc --session S [--frame N | --after SEC] [--collect-only] | sqtt --session S
tcc bench run --game SLUG --profile P [--runs N=3] | summarize --session S
tcc lab list | new NAME | build | run --exp E --driver D [--runs N=5] [--vopd on|off] | isa --exp E --driver D | compare --exp E [--drivers ...]
tcc report session S [--out MD] | cohort [--games a,b,c]
tcc mesa build --variant {stock,custom}         # thin wrapper over scripts/*.sh
```

## 5. Key component specs

**`bin/tcc-launch.sh`** (one-time human setup: each Steam game's launch options set to `<abs path>/bin/tcc-launch.sh %command%` — never touched again). Contract: **must never break a launch** — every step failure falls through to `exec "$@"`.
1. No `~/.tcc/armed.env` → `exec "$@"`. 2. Past `TCC_EXPIRES_EPOCH` → log stale, `exec "$@"`. 3. `$SteamAppId` set and ≠ `TCC_APPID` → `exec "$@"` (wrong game; don't contaminate). 4. Export sanitized `^[A-Z_][A-Z0-9_]*=` lines. 5. Write launch log (date, appid, applied env, argv) to `$TCC_LOG_DIR`. 6. One-shot → `mv armed.env armed.env.used` (+ json). 7. `TCC_MANGOHUD=1` && mangohud on PATH → `exec mangohud "$@"` else `exec "$@"`. Non-Steam/CLI launches reuse the same wrapper via `tcc launch`.

**C++ harness** (`shaderlab/harness/main.cpp`, 300–500 lines, `g++ -O2 -std=c++17 -lvulkan`, no CMake):
CLI `tcc-dispatch --spv F --groups X Y Z --iterations N --warmup M --buffer BYTES... --push-floats a,b --json OUT`. Creates instance (honors VK_ICD_FILENAMES), prints device name + driverInfo into output JSON (**this verifies stock vs custom actually loaded**), SSBOs at set0 bindings 0..N-1, timestamp query pair per dispatch, one submit+fence per iteration, ticks→ns via timestampPeriod. Output: device, driver_info, spv_sha256, per_iter_ns[], median/min/mean/stddev, readback_checksum (guards against "did nothing").

**Experiment** `shaderlab/experiments/NNN_name/`: `shader.comp` + `experiment.toml` (`[dispatch]` groups, local_size, iterations, warmup; `[buffers]` sizes_bytes, init; `[push_constants]`). Outputs → `data/shaderlab/<exp>/<driver>[_flags]/{run.json, shader.spv, synth.foz, isa.txt, stats.json}`.

**Lab A/B/C flow**: glslangValidator once → per driver in {stock, custom, llvm(=stock ICD + RADV_DEBUG=llvm), system}: harness runs N× + `fossilize-synth` → `fossilize-disasm --target isa` + `fossilize-replay --enable-pipeline-stats` under same env → `lab compare` table: median_ns (Δ% vs stock), vgprs, max_waves, code_size, stall_ratio, vopd_ratio, instr count.

**Stats-first canonical workflow** (replaces 2GB log parsing; encoded in docs/WORKFLOWS.md):
session new → foz snapshot before → arm → launch → play/bench → foz snapshot after → delta → extract (scene.foz) → stats run (stock + custom) → mine --top 25 → isa extract --top 25 (both drivers) → isa metrics [--deep] → compare → rga run --top 10 → report session. Old Track C disappears: hashes are exact end-to-end; frametime + static evidence join at session/cohort level in report.py.

## 6. Cleanup / migration (ordered; on branch `rework`)

1. `git checkout -b rework`.
2. Attic (git mv, one commit): `scripts/analysis_pipeline`→`_attic/analysis_pipeline`; `analysis`→`_attic/analysis`; `extract.py`, `src/triage.py`, `src/hazards.py`→`_attic/prototypes/`; `scripts/{gpu_test_runner,test_fossilize}.sh`→`_attic/shell/`; `git rm scripts/__init__.py`; absorb `todo` into docs/THESIS_NOTES.md then `git rm todo`; write `_attic/README.md`.
3. Data moves (untracked, plain mv): mkdir `data/{archive,sessions,foz/remnant2,shaderlab} tools`; `isa_dumps/raw_dump.log`→`data/archive/`; `rdna3_pipeline_samples.json`→`data/archive/`; `src/shaders/remnant2/steamapp_pipeline_cache.foz`→`data/foz/remnant2/`; then `rm -rf src isa_dumps logs __pycache__` (verify nothing tracked remains in src/ first).
4. **[HUMAN confirm]** `rm -rf gfxreconstruct radeon_gpu_analyzer` (~2.4GB freed).
5. New `.gitignore`.
6. **[HUMAN]** download AMD prebuilt RGA Linux tarball → `tools/rga/`; record version in docs/SETUP.md.
7. Scaffold new tree; port old `analysis/schemas/*.json` concepts into `src/tcc/schemas/` (reference only — no runtime imports from _attic).

## 7. Phases & acceptance criteria

- **Phase 0 — Restructure**: §6 steps + empty package (`tcc --version`, doctor stub). ✓ `pip install -e .` in build/venv works; git status clean; tree matches §1.
- **Phase 1 — Core** (config, paths, session, provenance, toolchain, doctor, session CLI, all TOMLs, schemas). ✓ `tcc doctor` shows fossilize tools as local + flags missing mangohud/renderdoc/rga with remedies; `tcc session new --game remnant2 --scene smoke` creates schema-valid session.
- **Phase 2 — Foz + stats engine** (foz.py, stats.py, mine.py + CLIs). **First task: run `fossilize-replay --enable-pipeline-stats` once against the Remnant II sample foz and adapt the parser to real output.** ✓ `tcc foz import` + `tcc stats run --driver stock` → stats.stock.csv with >100 rows, non-null vgprs/max_waves; `tcc mine --top 10` ranked table. (GPU required.)
- **Phase 3 — Arm/launch** (arm.py, steam.py, wrapper). Test with vkcube via a `vkcube.toml` native-cli config before any Steam game. ✓ `tcc arm --profile custom && bin/tcc-launch.sh vkcube` log shows custom ICD + one-shot consumed; stale/absent profile → vkcube untouched; **[HUMAN]** one Steam game launches normally through wrapper.
- **Phase 4 — ISA/compare/RGA** (isa.py, hazards port, compare.py, rga.py + CLIs). ✓ isa extract top-5 both drivers; metrics reproduce triage columns; **`tcc compare --a stock --b custom` reports ZERO deltas (custom layer is unmodified — this IS the sanity check)**; rga returns gfx1101 live-VGPR numbers.
- **Phase 5 — Shaderlab** (harness, lab.py, 000_smoke + 001_vopd_saturation). ✓ `lab build` compiles; smoke run emits plausible median_ns + correct device string; vopd experiment shows different vopd_ratio between stock and llvm; `--vopd on|off` measurably changes v_dual counts.
- **Phase 6 — Bench + capture** (bench.py, renderdoc_ctl.py + CLIs). **[HUMAN]** apt install mangohud renderdoc; install Wukong bench tool + FFXV bench; run actual benchmarks. ✓ `tcc bench run --game vkmark --profile stock --runs 3` fully unattended → bench_summary.json; one Steam-game session end-to-end (arm→launch→bench→foz delta→stats) with all artifacts registered; `capture rdc --collect-only` registers a hotkey .rdc.
- **Phase 7 — Reports + docs** (report.py, SETUP/WORKFLOWS/GAMES/THESIS_NOTES, README/AGENTS rewrite). ✓ `tcc report session @last` is a self-contained thesis-usable markdown; docs contain exact one-time Steam setup string + per-game bench instructions.

**Human-only tasks**: sudo installs (mangohud, renderdoc, vkmark), RGA + GravityMark downloads, Steam launch-options one-time setup per game, game installs (Cyberpunk, SOTTR, Wukong bench, FFXV bench, Control), running manual scenes / menu benchmarks, confirming the 2.4GB deletions.

## 8. Risks & mitigations

1. **pipeline-stats output format unverified** → Phase 2 opens with run-once-inspect-adapt; parser is substring-tolerant with `extra` column; fallback = targeted `RADV_DEBUG=shaders` replay of scene.foz only (small logs).
2. **fossilize-disasm needs live driver** (help says `state.json` positional — verify it accepts .foz; it runs the real device) → env-injected ICD by design; per-hash skip-and-record on failure (esp. RT pipelines); mine works from stats alone.
3. **renderdoc python module may not ship in Ubuntu package** → Backend B (hotkey + collect) is the guaranteed path; doctor reports which backend is live.
4. **VKD3D foz replay quirks** (Cyberpunk/Wukong/Remnant RT pipelines) → --timeout-seconds + per-pipeline failure tolerance; SOTTR (native Vulkan) + synthetics anchor the method.
5. **FFXV/Wukong Proton quirks** (launchers break --wait) → best-effort wait + operator Enter-to-continue; record quirks in docs/GAMES.md. **Verify Wukong bench appid from Steam at implementation time.**
6. **$SteamAppId absence in pressure-vessel** → guard degrades to TTL+one-shot (still safe); verify in Phase 3.
7. **Cache pollution corrupting A/B** → `profile_env` centrally forces nocache + isolated MESA_SHADER_CACHE_DIR for all stats/lab/disasm invocations.
8. 32-bit titles out of scope (wrapper sets x86_64 ICD only) — note in GAMES.md.

## 9. Verification (end-to-end)

- After Phase 2: full stats pipeline on the existing Remnant II sample foz — no game launch needed.
- After Phase 3: vkcube armed-launch proves ICD swap + one-shot without touching Steam.
- After Phase 4: stock-vs-custom compare = zero deltas (ground truth, since custom is unmodified).
- After Phase 5: `001_vopd_saturation` stock-vs-llvm shows nonzero vopd_ratio difference — first real thesis data point.
- After Phase 6: one complete real-game session (Remnant II ward13 or a benchmark title) producing session report with foz delta, stats A/B, top-offender ISA, bench summary.

## Reference files (read before implementing)

- `_attic/analysis_pipeline/common/session_lib.py` — session/manifest/registry concepts to port.
- `_attic/prototypes/triage.py` — exact stall_ratio/vopd_ratio formulas (keep names).
- `_attic/prototypes/hazards.py` — DAG model to port into `tcc/hazards.py`.
- `_attic/shell/{gpu_test_runner.sh,test_fossilize.sh}` — env conventions (RADV_DEBUG=shaders,hang,nocache; ICD swap; LLVM via RADV_DEBUG=llvm) reused in `config.profile_env` and lab flow.

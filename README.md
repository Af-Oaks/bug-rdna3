# RDNA3 Gain-Variability Thesis Workflow

Investigates **which workload, pipeline, shader, compiler and runtime characteristics correlate
with high versus low gains on RDNA3** relative to RDNA2-era expectations. Not a search for an
architectural flaw — a measurement of where the gains go.

Target: AMD Radeon RX 7800 XT — Navi 32 — ISA target **`gfx1101`** (not gfx1100, which is Navi 31).
Stack: Ubuntu 24.04, Steam/Proton, Vulkan, Mesa RADV/ACO, with a stock and a custom local Mesa build.

## Start here

| file | what it holds |
|---|---|
| **[ONGOING.md](ONGOING.md)** | **live context — read first.** Where the work stopped, the next command, what result is expected, open questions |
| [TODO.md](TODO.md) | phase tracker: done vs left, human-only tasks, standing facts |
| [AGENTS.md](AGENTS.md) | working rules and hard-won constraints for anyone (human or agent) touching this repo |
| [DOMAIN.md](DOMAIN.md) | the microarchitectural background: `s_delay_alu`, VOPD dual-issue, occupancy |
| [docs/PLAN.md](docs/PLAN.md) | the approved repo/tooling plan (phases 0–7) |
| [docs/METRICS_PLAN.md](docs/METRICS_PLAN.md) | Metrics 1 & 2: static compiler stats + runtime FPS, and the calibration bridge |
| [docs/SHADERBENCH_PLAN.md](docs/SHADERBENCH_PLAN.md) | Metric 3: executing shaders extracted from game `.foz` files as a deterministic benchmark |

## The three metrics

1. **Static compiler efficiency** — replay a captured `.foz` through stock and custom RADV with
   `fossilize-replay --enable-pipeline-stats`; diff per-stage VGPRs, occupancy, spills, VOPD,
   instruction mix. Game-free, deterministic, minutes.
2. **Runtime impact** — run the game's built-in benchmark under MangoHud for real FPS and
   frametime percentiles. The oracle, but noisy and slow.
3. **Shaderbench** — take the real shaders out of the `.foz` and execute them standalone under a
   fixed synthetic load with GPU timestamps. Deterministic like (1), but measures actual GPU
   cost like (2). This is what makes a 2% compiler win visible at all.

All three feed a **ledger** keyed by (workload × compiler revision), so a compiler change can be
followed from "the compiler emitted better code" to "the shader got faster" to "the frame got
faster" — or shown not to survive that chain.

## Layout

```
src/
├── cli.py             CLI entry point (`tcc`)
├── core/              config, paths, session, provenance, util, toolchain, schemas/
├── shader_extractor/  foz.py — snapshot / delta / prune / extract from Steam caches
├── analysis/          stats.py, mine.py        (later compare.py, isa.py, hazards.py)
├── benchmark/         game_bench.py            (later shaderbench.py, ledger.py)
└── launcher/          arm.py, steam.py — the armed-profile launch path

config/             tracked TOML: tcc.toml, games/*.toml, profiles/*.toml
bin/tcc-launch.sh   Steam %command% wrapper (reads ~/.tcc/armed.env)
shaderlab/          C++ Vulkan harness + authored GLSL experiments
scripts/            setup_env.sh, build_custom_aco.sh
custom_mesa_layer/  the ACO experiment overlay
docs/               plans and thesis notes
data/               gitignored: sessions, corpus, ledger, foz caches
build/, lib/        gitignored: local Mesa + Fossilize builds and vendored sources
```

## Quick start

```bash
./build/venv/bin/pip install -e .
./build/venv/bin/tcc doctor                      # verify toolchain, ICDs, game caches
./build/venv/bin/tcc session new --game control --scene central-executive-atrium
./build/venv/bin/tcc bench run --game control --profile bench-mangohud
```

Steam launch options are set **once per game** to `<repo>/bin/tcc-launch.sh %command%`; every
experiment after that is `tcc arm --profile <name>` followed by a normal launch. Profiles swap
the driver ICD, RADV flags, capture layers and MangoHud settings — Steam is never edited again.

## License

See [LICENSE](LICENSE).

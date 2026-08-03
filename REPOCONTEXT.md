# Project Rules

Custom rules for this repository. `AGENTS.md` §0.8 points here; these complement
it and win on conflict. The mechanism is in [DOMAIN.md](DOMAIN.md), live status
in [ONGOING.md](ONGOING.md), the queue in [TODO.md](TODO.md).

This repo is a thesis workspace measuring why AMD RDNA3 shows uneven
gen-over-gen gains. Target: RX 7800 XT, Navi 32, **gfx1101**.

## Read in this order

1. **[ONGOING.md](ONGOING.md)** — where we stopped, what runs next. Read FIRST.
2. **[DOMAIN.md](DOMAIN.md)** — what a `.foz` is, why replay recompiles, what the
   columns mean, what the hypotheses are and where they stand.
3. **[src/CONTEXT.md](src/CONTEXT.md)** — the code, explained per folder.
4. **[TODO.md](TODO.md)** — the queue. Method lives in `docs/`:
   [THESIS_NOTES.md](docs/THESIS_NOTES.md) and
   [METRICS_CATALOG.md](docs/METRICS_CATALOG.md).

## Layout

- `src/` — contextual top-level packages, no umbrella package. Entry point
  `tcc` is `src/cli.py`, installed in `build/venv`, run as `./build/venv/bin/tcc`.
  - `core/` — config, paths, session, provenance, errors, gpuguard, toolchain, `schemas/`
  - `shader_extractor/` — `foz.py`, `collect.py`, `corpus.py`
  - `analysis/` — `stats.py`, `mine.py`, `compare.py`, `isa.py`, `chart.py`
  - `benchmark/` — `game_bench.py`, `shaderbench.py`, `ledger.py`
  - `launcher/` — `arm.py`, `steam.py`
- `config/` — `tcc.toml`, `games/*.toml` (the matrix), `profiles/*.toml`.
- `bin/tcc-launch.sh` — the Steam `%command%` wrapper.
- `data/` — gitignored: `sessions/`, `foz/` (verified archive), `corpus/` (merged).
- `custom_mesa_layer/` + `scripts/build_custom_aco.sh` — the ACO experiment area.
- `shaderlab/` — the C++ GPU harness (Metric 3). Carries its own `CONTEXT.md`
  under the same protocol as the `src/` packages.
- `shaderlab/harness/` — the Metric 3 C++ executor; `build.sh` is one `g++` call.

New modules go in the package that owns the concept. Do not create an umbrella
package.

## Code rules

- **No dead code.** A function nothing calls gets deleted or gets a caller in the
  same change. Same for config keys: a key nothing reads is worse than dead code
  because it *looks* like a control.
- **No compatibility layers**, no shims, no fallbacks, no defaults defending
  against states the schema forbids. If the data is malformed, fail loudly.
  Two things that look like compat and are not — **do not delete them**:
  the dual `.foz` layout handling (both layouts are live on these drives) and
  `_classify_column`'s substring matching (forward-compat for a vendored tool
  we rebuild).
- **One owner per decision.** No second implementation of a rule that already
  exists elsewhere — filename flattening, foz selection, environment building.
- **Every user-facing error subclasses `core.errors.TccError`.** Programming
  errors must not: those should crash with a traceback.
- **No stubs.** Planned work lives in `TODO.md`, not in argparse. Fifteen stub
  parsers were deleted 2026-08-03 because `--help` advertising six command groups
  that all exit 2 is worse than a short help listing.

## Measurement rules

- Everything is session-scoped. Artifacts land in
  `data/sessions/<game>/<session_id>/` with sha256 provenance and step records.
- **Every subprocess whose output could reach the thesis goes through
  `provenance.run_recorded()`** — it records the environment the child actually
  received, which is the only machine-checkable record of which compiler produced
  a number. Snapshot the child's env, never `os.environ`.
- **Every Vulkan environment comes from `config.profile_env()`.** Never build one
  by hand. A/B runs are cache-clean by construction: `RADV_DEBUG=nocache` plus an
  isolated `MESA_SHADER_CACHE_DIR`.
- **Analyse the merged corpus, not one file.** `tcc corpus build` first;
  `resolve_foz()` prefers it. Selection is never by mtime.
- Launch experiments via the armed profile. Never edit Steam launch options
  per-experiment — they are set once to the wrapper.
- Label uncertainty. Heuristic linkage is never implied as exact.

## Non-goals — hard lessons, do not relitigate

- Do NOT reintroduce GFXReconstruct or hand-inject Vulkan layers into Proton
  (32-bit pre-loader panics, VKD3D allocator collisions, pressure-vessel path
  blocks). Use `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`.
- Do NOT parse multi-GB `RADV_DEBUG=shaders` dumps. The driver reports the stats.
- Do NOT claim a `.foz` reconstructs scene state, or that a mined pipeline was
  drawn, without RenderDoc evidence.
- Do NOT resolve Steam caches by globbing `~/.local/share/Steam` — games live
  across several libraries. Go through `steam.library_folders()`.
- Do NOT treat every new hash in a delta as created by this run. Use
  `run_created`.
- Do NOT put automation state in `/tmp` for Proton games. `$HOME` only.
- Do NOT build a keep-only-N database with `fossilize-prune --skip` — it is
  silently wrong above ~1000 hashes.
- Do NOT add cloud services or external databases.
- Do NOT run untrusted GPU work in-process. A GPUVM fault destroys the device
  and takes every later pipeline with it — go through `core.gpuguard`.
- Do NOT expect Metric 3 to cover vkd3d/DX12 titles. Their shaders read raw
  pointers out of descriptor heaps and fault when isolated (measured 0/8).

## ONGOING.md protocol (mandatory)

Written **for the human between sessions**, not for the agent. Update it after
every prompt, before ending the turn: bump the date and branch/commit line; say
what was just done and what it proved, with the numbers or paths that back it;
give the single next command and what result is expected; keep "built vs missing"
honest; delete resolved open questions rather than letting them rot.

No invented results — if something was not run, say "not run". Distinguish
*implemented* from *tested on the GPU* from *committed*. **Strictly under 150
lines**: delete resolved items instead of appending. Durable facts graduate to
`DOMAIN.md` (mechanism), `TODO.md` (plan) or the folder's `CONTEXT.md`.

## Folder CONTEXT.md protocol (mandatory)

Every folder under `src/` carries a `CONTEXT.md`, written **for a human reading
the code for the first time** — the author six months later, an advisor, an
examiner. Not agent scaffolding, not an API reference.

**Intention over implementation.** Explain what the code is *for*, which decision
it encodes, and what breaks if someone changes it. Never paraphrase what the
functions do — the code says that already, and the paraphrase rots. If a sentence
would still be true after deleting the implementation, it belongs; if it restates
a signature, cut it.

**Every file ends with "Known problems, costs, and things I would flag":** real
defects, dead code, stale comments, costs that will bite at a stated scale, gaps
between what a docstring claims and what the code does — and **self-notes**,
where I was asked for approach X, complied, and it still carries a cost worth
naming. Complying and staying quiet is the failure mode this section prevents.

Every claim must be verifiable from the code as it stands; quoted numbers must
come from a real recorded run. Delete an item when it is fixed — do not keep a
changelog of resolved problems.

**Update obligation:** a change under `src/<pkg>/` updates `src/<pkg>/CONTEXT.md`
in the *same* change. A new folder is created with its `CONTEXT.md` and gains a
row in `src/CONTEXT.md`.

Style follows `AGENTS.md` §9, with §10.1 in force — these are explanatory, so
they run as long as the topic needs and use headers for skimming. English always.

## Useful assets

- `data/foz/` — 22.95 GB, 18 games, sha256-verified. ⚠️ Run
  `tcc collect --check` before uninstalling anything; as of 2026-08-03, 10 of 18
  games held data that was not yet saved.
- Fossilize CLIs in `build/install/bin/`. RGA arrives as a tarball in `tools/rga/`.
- RDNA2/RDNA3 ISA reference PDFs in `pdf_context/`.

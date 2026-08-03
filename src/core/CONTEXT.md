# `core/` — the plumbing everything else stands on

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/core/` updates this file in the
> same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this package exists

Nothing in here knows what a shader is. `core` answers four questions that every
other package would otherwise answer differently:

- **Where does this file go?** (`paths.py`)
- **What environment does this run get?** (`config.py`)
- **What is this run, and what belongs to it?** (`session.py`)
- **How do we prove it happened?** (`provenance.py`, `toolchain.py`)

The thesis lives or dies on the last one. A number that cannot be traced back to
a command, an environment and a log is not evidence, it is an anecdote.

## The files

### `paths.py` — pure location resolution

Every function is pure: no TOML loading, no side effects beyond `stat`. That
purity is the whole point — `config.py` imports it, so if `paths.py` ever
imported config back you would have a cycle. Keep it dependency-free.

`repo_root()` walks up from its own file looking for `pyproject.toml`, so the
tool works from any working directory and fails loudly if installed outside its
source checkout.

### `config.py` — three TOML families, and one choke point

Three kinds of configuration, all tracked in git under `config/`:

- `tcc.toml` — global paths and defaults.
- `games/<slug>.toml` — the game matrix. One file per title: appid, engine, API,
  cohort (high-gain / low-gain / synthetic / reference), how its benchmark is
  triggered, and where its shader cache is.
- `profiles/<name>.toml` — an experiment variant: which driver, which
  `RADV_DEBUG` / `RADV_PERFTEST` flags, whether MangoHud or RenderDoc is on.

Then there is **`profile_env()`, which is the reason this module matters.** It is
the single place environment variables get computed for any Vulkan invocation.
Not a convenience — a correctness gate. An A/B comparison where one side quietly
reuses a warm pipeline cache is not wrong-looking, it is wrong-and-plausible.
Centralising means `nocache` and an isolated `MESA_SHADER_CACHE_DIR` cannot be
forgotten by a caller written six months from now. `force_nocache` defaults to
`True` for exactly that reason; real gameplay launches must opt out explicitly.

### `session.py` — the unit of reproducibility

A session is a directory: `data/sessions/<game>/<YYYYMMDD-HHMMSS>_<game>_<scene>/`
with fixed subdirectories (`logs/ foz/ stats/ isa/ captures/ bench/ reports/`…).

Two files describe it. `session.json` is the manifest — what this run is, which
profiles it used, and an append-only list of every step executed. `artifacts.json`
is the registry — every file produced, with its sha256, its producer, and a
**confidence label** (`exact` / `strong` / `weak` / `unresolved`). That last field
exists because parts of this investigation are heuristic linkage, and the repo
rule is that heuristics are labelled, never implied as exact.

Both are validated against JSON Schema on every save, so a malformed manifest
fails at write time instead of three weeks later during analysis.

Session references are forgiving on purpose: `@last`, a full id, or any unique
substring. Ambiguity raises rather than guessing.

### `provenance.py` — proof

`sha256_file()` for content identity. `env_snapshot()` captures only the prefixes
that can change a result (`VK_`, `RADV_`, `MESA_`, `ENABLE_VULKAN_`, `AMD_`,
`TCC_`) — a full environment dump would bury the four variables that matter.

`run_recorded()` is the important one: it runs a subprocess, tees stdout and
stderr both to the terminal and into `logs/<step>.{stdout,stderr}.log`, and
appends a step record with argv, duration, return code, timeout flag and the
environment snapshot. Use it for anything whose output could ever end up in the
thesis.

### `toolchain.py` — what is actually installed

Resolution order is deliberate: `build/install/bin` (the local Mesa/Fossilize
build) → `tools/**` (vendored) → `PATH` (system). Local wins because the whole
project depends on running *specific* builds, not whatever the distro shipped.

`doctor()` is the health check: Fossilize CLIs, required system tools, optional
tools with a remedy line each, both Mesa ICDs, `~/.tcc` writability, the launch
wrapper, per-game shader cache presence, and the Python dependencies. Exit code
1 if anything is `missing`; `warn` does not fail the check.

### `util.py`

Three functions: `ensure_dir`, `read_json`, `write_json`. It stays this small on
purpose — AGENTS.md §4 bans collecting helpers into a `*Utils` bag. If something
here grows a domain concept, it moves to the package that owns that concept.

## Ground rules a future change must not break

- `paths.py` imports nothing from this package.
- Any new Vulkan invocation gets its environment from `profile_env()`. No
  exceptions, no local `os.environ` edits.
- Anything written to disk that a later step reads gets registered with
  `record_artifact()`.
- Confidence labels are not decoration. `exact` means the file is what it claims
  to be; anything inferred is `strong` at best.

## Known problems, costs, and things I would flag

1. **Two sources of truth for paths, and one of them is dead.**
   `paths.steam_root()` and `paths.armed_profile_path()` hardcode locations,
   while `config.Paths` reads the *same* two keys from `tcc.toml`. Nothing calls
   `paths.steam_root()` at all — so `$TCC_STEAM_ROOT`, documented in its
   docstring as a testing override, has **zero effect** on anything;
   `steam.library_folders()` reads the TOML value. Symmetrically, nothing reads
   `cfg.paths.armed_profile` — `arm.py` uses the hardcoded
   `paths.armed_profile_path()`. Editing `armed_profile` in `tcc.toml` silently
   does nothing. Pick one owner per path and delete the other.
2. **`data_dir` is split the same way.** `session.py` uses `paths.data_dir()`
   (hardcoded `repo_root()/data`); `collect.py` uses `cfg.paths.data_dir` (from
   TOML). Point `data_dir` at another drive and your sessions and your collected
   `.foz` corpus land in different roots, with nothing warning you.
3. **`session.save()` is O(everything) and gets called constantly.** Each save
   re-reads *and re-parses both JSON Schema files from disk*, then rewrites the
   whole manifest and the whole registry. `record_step`, `record_artifact`,
   `add_note`, `use_profile` and `close` all call it. Snapshotting N `.foz`
   files means N full manifest rewrites plus 2N schema loads plus N sha256
   passes over multi-GB files. At today's scale (18 games, tens of artifacts)
   this is invisible. It is the first thing to profile if any loop ever records
   thousands of artifacts — the fix is a module-level schema cache and a
   `save(defer=True)` batch mode, and neither exists yet.
4. **`toolchain._foz_cache_hits(cfg, game_cfg)` never uses `cfg`.** Dead
   parameter, dead argument at the call site.
5. **`run_recorded()` always mirrors child output to the terminal.** There is no
   quiet mode. Fine for interactive use; it means a future batch job over the
   22.95 GB corpus will spray replay output across the console with no way to
   suppress it short of shell redirection.
6. **There is no test suite in this repository at all.** Not for `core`, not
   anywhere — `find . -name "test_*.py"` outside `lib/` and `build/` returns
   nothing. AGENTS.md §6 instructs running the full suite as a baseline before
   starting work; there is no suite to run. Every "verified" claim in ONGOING.md
   is a manual run someone did once and wrote down. `session.py` and
   `config.profile_env()` are the two places where a silent regression would
   corrupt results rather than crash, and they are exactly the two places a
   twenty-line test file would pay for itself.

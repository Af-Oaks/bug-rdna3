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

### `gpuguard.py` — survive a compiler change that hangs the GPU

Aggressive ACO changes do not crash cleanly; they produce shaders that fault on
a bad address, which loses the Vulkan queue and can take the desktop with it.
Three rules, enforced here so no caller has to remember them:

1. **Never run untrusted GPU work in the session manager's process.** A queue
   loss kills whoever holds the device — if that is also the process holding the
   session, the run's records die with it. Everything goes through a subprocess
   with a hard timeout, SIGKILLed rather than SIGTERMed because a process wedged
   on a lost queue is in an uninterruptible wait.
2. **A GPU reset is a RESULT, not a failure to hide.** `status` is
   ok / timeout / gpu_reset / crashed and never collapses to a bool.
3. **`gpu_reset_detected` is three-valued.** `dmesg` is usually restricted, so
   "no reset found" and "not allowed to look" must not be the same answer —
   None means could-not-check.

Proven in anger: the SB-0 spike faulted the GPU on eight consecutive Remnant II
shaders and the desktop never noticed.

### `gpuguard.py` — do not lose the machine to a bad shader

Aggressive ACO changes do not crash cleanly; they hang the GPU, and a lost queue
can take the desktop. Three rules, enforced here: untrusted GPU work runs in a
**separate process** with a hard timeout, never in the process holding the
session; a GPU reset is a **result** with its own status, not a failure to hide;
and detection is honest — `gpu_reset_detected` is three-valued, because `dmesg`
is often unreadable and "no reset found" must not be confused with "could not
look". In practice RADV prints `GPUVM fault` to the child's stderr, which is the
more reliable signal of the two.

### `errors.py`

One base class, `TccError`. `cli.main()` catches it once. The explicit tuple it
replaced had to be edited from a distance and went stale twice, so two error
types reached users as tracebacks. Anything raised for a condition the user can
act on subclasses it; programming errors deliberately do not, because those
should crash loudly.

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

1. **`session.save()` still rewrites both files in full on every call**, and
   `record_step` / `record_artifact` / `add_note` / `use_profile` / `record_tool`
   all call it. The schema parsing is now cached, so the remaining cost is the
   JSON write — invisible at tens of artifacts, worth batching the day a loop
   records thousands.
2. **`data_dir` has two owners.** `session.py` uses `paths.data_dir()` (hardcoded
   `repo_root()/data`); `collect.py` and `corpus.py` use `cfg.paths.data_dir`
   from TOML. Point the TOML elsewhere and sessions and the foz archive land in
   different roots with nothing warning you. One of the two should go.
3. **`run_recorded()` always mirrors child output to the terminal.** There is no
   quiet mode, so a background job over the 22.95 GB corpus sprays replay output
   with no way to suppress it short of shell redirection.
4. **`gpu_arch` in `tcc.toml` is read by nothing yet.** Kept deliberately: it is
   what `rga.py` / `isa.py` will pass as RGA's `--asic`. The TOML comment says
   so, so it does not read as a live control.

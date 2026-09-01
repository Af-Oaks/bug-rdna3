# `src/` — the map

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/` updates this file in the same
> commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## What lives here

One Python source root, split into packages named after the *concept* they own.
There is no umbrella `tcc` package — it was removed on 2026-07-28 because every
import read `tcc.tcc.something` and told you nothing about what the module did.

| folder | owns | read |
|---|---|---|
| `core/` | plumbing: where files go, what environment a run gets, what happened | [core/CONTEXT.md](core/CONTEXT.md) |
| `shader_extractor/` | getting shaders out of games without instrumenting them | [shader_extractor/CONTEXT.md](shader_extractor/CONTEXT.md) |
| `analysis/` | turning compiler output into numbers you can defend (Metric 1) | [analysis/CONTEXT.md](analysis/CONTEXT.md) |
| `benchmark/` | what the player actually sees (Metric 2), later Metric 3 | [benchmark/CONTEXT.md](benchmark/CONTEXT.md) |
| `launcher/` | forcing a chosen driver into a game you do not control | [launcher/CONTEXT.md](launcher/CONTEXT.md) |
| `../shaderlab/harness/` | the Metric 3 C++ executor (outside `src/`, built by `build.sh`) | [../shaderlab/CONTEXT.md](../shaderlab/CONTEXT.md) |
| `core/schemas/` | the written-down shape of files that outlive a session | [core/schemas/CONTEXT.md](core/schemas/CONTEXT.md) |

A new module goes in the package that owns its concept. If it does not fit any
of them, that is a signal the concept is new — argue for a new package rather
than dropping it in `core/`.

## `cli.py` — the only entry point

`tcc` is one binary, installed from `pyproject.toml` as `cli:main`, run in
practice as `./build/venv/bin/tcc`.

The intention behind its shape is worth stating, because it looks odd:

**Every subcommand from the approved plan exists as a real parser today**, even
the ones nobody has written yet. `tcc lab run --help` works and shows the exact
flags it will accept; the handler prints `not implemented yet (Phase 5)` and
exits 2. The reasoning was that the command surface is a design decision made
once, and scripts or notes written against the final surface should not need
rewriting when the implementation lands.

Handlers are deliberately thin — parse arguments, call one module function,
print. No logic lives in `cli.py`. If a handler starts making decisions, those
decisions belong in the package that owns the concept.

Failure handling is centralised: `main()` wraps the dispatch in one `try` and
converts **`TccError`** — the base class every user-facing error subclasses —
into `error: <message>` on stderr with exit 1. It used to catch an explicit
tuple of seven types, which went stale twice: `CompareError` and `CollectError`
both reached users as tracebacks. Programming errors deliberately do *not*
subclass `TccError` — those should crash with a traceback, because they are bugs
rather than messages.

## How a normal session flows

```
tcc doctor                      # is the toolchain real?
tcc collect --check             # would I lose anything by uninstalling?
tcc corpus build --game X       # merge every collected .foz into one database
tcc session new --game X ...    # everything below lands under this session
tcc bench run --game X ...      # arm → launch → play → foz delta → FPS summary
tcc stats run --driver stock    # replay the captured pipelines, get compiler stats
tcc stats run --driver custom
tcc compare --a stock --b custom
```

`core` underlies every step; `launcher` owns the third; `shader_extractor`
feeds the fourth; `analysis` owns the last two.

## Known problems, costs, and things I would flag

1. **`bin/tcc-launch.sh` is gitignored.** `.gitignore` excludes `bin/` as a build
   directory, but the wrapper is 115 lines of hand-written, acceptance-tested
   source implementing half the armed-profile contract — the half that runs
   inside pressure-vessel. The Python side is versioned; its counterpart is not,
   and is one `rm` from gone.
2. **There is no test suite.** `find . -name "test_*.py"` outside `lib/` and
   `build/` returns nothing. AGENTS.md §6 says run the suite as a baseline;
   there is none. The two places a silent regression would corrupt results
   rather than crash are `config.profile_env()` (if `nocache` ever stops being
   appended, every A/B compares warm against cold) and
   `stats._classify_column()` (correctness depends on branch order, and it has
   already produced one wrong-column bug). A thirty-minute fixture file would
   cover both.
3. **`--help` is honest now, but the planned surface lives only in prose.**
   Deleting the stub parsers removed the lie that `tcc` could do six things it
   could not; the cost is that the intended command surface is now discoverable
   only by reading `docs/`. That was the trade, and it is the right one, but it
   is a trade.

# `shader_extractor/` — getting real shaders out of real games

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/shader_extractor/` updates this
> file in the same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this package exists

The thesis needs shaders that shipped games actually compile — not synthetic
ones. Getting them could have meant hooking Vulkan, injecting layers into
Proton, or parsing driver dumps. All three were tried and all three failed
(32-bit pre-loader panics, VKD3D allocator collisions, multi-GB text dumps).

The approach that works needs no instrumentation at all: **Steam's own Fossilize
layer already records every pipeline every game creates.** Playing the game *is*
the capture step. This package's whole job is to find those databases, copy them
somewhere durable before Steam wipes them, and slice them into something small
enough to analyse.

## The one conceptual trap

A `.foz` records pipeline **creation**, not draws. A pipeline in the database was
compiled at some point; it was not necessarily used in the frame you care about,
and the database says nothing about scene state. RenderDoc frames are the only
ground truth for "this shader was on screen". Never let a `.foz` claim otherwise
in writing.

The second trap is the same shape: a hash that is new in an after-snapshot was
not necessarily created by your run. Steam can download its community pre-built
cache *mid-session* — this was observed live with Metro EE, where a 142 MB
pre-cache landed while the benchmark was running. That is why `delta()` reports
`new` and `run_created` as separate numbers, and why thesis analysis uses
`run_created`.

## The files

### `foz.py` — every operation on a Fossilize database

`snapshot()` copies the game's caches into the session, labelled `before` or
`after`. `delta()` diffs the hash sets per tag (modules / graphics / compute /
raytracing) and writes `delta.json`. `extract()` builds a scene-scoped
`scene.foz`. `replay_stats()` runs the replayer with `--enable-pipeline-stats`.
`disasm()` pulls the RDNA ISA for one pipeline.

**The module docstring is the most valuable thing in this package**, and it is
not documentation of the code — it is documentation of the *tools*, learned the
hard way against a real 129 MB Remnant II database:

- `fossilize-prune --skip-<type>` is reliable for hundreds of hashes and
  silently wrong for thousands. Skipping all-but-one of 5,035 graphics hashes
  left 78 survivors instead of 1. Do not build a keep-only-N database by
  skipping the complement.
- `fossilize-prune --filter-<type>` *does* guarantee the requested hashes
  survive, but drags along ~77–87 unrelated pipelines regardless of what you
  asked for — even a nonexistent hash produced ~77 survivors.
- `fossilize-disasm` accepts a `.foz` directly, despite its own `--help` saying
  it wants `state.json`. Its `--filter-<type>` has *different* semantics from
  prune's: exactly the one requested pipeline, no companions.
- `--target isa` emits three sections per file — NIR, ACO IR, and Final
  Assembly. The last one is the real RDNA ISA that Phase 4 will parse.

That block is why `extract()` chooses filter over skip and then verifies
presence with a hard error. Silent data loss in a scene database would poison
every number downstream, so it crashes instead.

### `collect.py` — save the corpus before Steam eats it

Shader caches live on the game's own drive and Steam wipes them whenever it
feels like it. `collect` copies them into `data/foz/<slug>/` with a sha256
verify on every file and a `manifest.json` recording where each came from.

It classifies every file into three kinds that are **not interchangeable as
evidence**:

- `run_recorded` (`steamapprun_*`) — recorded by launches on this machine. The
  only class that proves the local GPU and driver compiled it.
- `steam_precache` — possibly Steam's downloaded community cache. Usable shader
  *material*, never evidence of what this machine ran.
- `whitelist` — Valve's curated set.

Everything else in a shadercache is deliberately skipped, and the reasons are
concrete: `mesa_shader_cache_sf` is RADV's compiled-blob cache rather than
pipeline create-infos, `replay_cache.*` is the replayer's own output, and
`transcoded_video.foz` is video — PRAGMATA ships 1.2 GB of it.

## Ground rules a future change must not break

- Cache lookup goes through `launcher/steam.py`. Never glob `~/.local/share/Steam`
  directly: games live across several library folders and each game's cache is
  in *its own* library.
- Both layouts must keep working — new `fozpipelinesv6/steam_pipeline_cache.foz`
  and legacy `steamapprun_pipeline_cache.<hex>/steamapp_pipeline_cache.foz`.
- The `steamapprun` marker must survive any renaming during copy, or
  `run_created` becomes meaningless.

## Known problems, costs, and things I would flag

1. **`run_created` rests on a substring that a rename could break, and the
   comment explaining it is wrong.** `delta()` decides which files are
   run-recorded with `"steamapprun" in f.name`, which works only because
   `snapshot()` prefixes the parent directory name into the copy. The comment
   in `delta()` says `snapshot()` "keeps the parent name only on collision" —
   it does not; it keeps the parent name whenever the parent is not
   `fozpipelinesv6`, and adds the *grandparent* on collision. Someone
   simplifying that naming rule would silently turn `run_created` into zero,
   and there is no test that would notice.
2. **`delta()` is the slow step and caches nothing.** It shells out to
   `fossilize-list` once per file per tag — four tags across every before and
   after file, each a full pass over a possibly multi-GB database. On the
   22.95 GB corpus that dominates the runtime, and re-running recomputes
   everything from scratch.
3. **`scene.foz` is a superset and must never be described as "the scene".**
   `extract()` knowingly accepts prune's ~80 bonus pipelines because stats and
   disasm only need the requested hashes to be present and loadable. That
   trade-off is fine for the tooling and *not* fine for a sentence in the
   thesis: the file contains the requested pipelines plus roughly eighty
   unrelated companions. Say that, or filter the stats table by the requested
   hash list afterwards.
4. **`collect.py` reads every source file in full even when it is about to skip
   it.** The skip decision is made by comparing sha256, so "re-running must be
   cheap" costs a complete read of all 22.95 GB, RE6's 6.5 GB included. Size
   plus mtime as a pre-filter would make the common case free. This is a
   deliberate correctness-over-speed choice — it just is not free, and the
   docstring's "re-running must be cheap" oversells it.
5. **`import os` sits inside two function bodies** (`replay_stats`, `disasm`)
   rather than at module scope, where every other import lives.
6. **`CollectError` subclasses `RuntimeError` and is not in `cli.main()`'s
   handled tuple**, so a collect failure that escapes `collect_all()`'s
   per-game catch prints a traceback instead of one clean error line.
7. **`corpus.py` does not exist yet.** ONGOING.md and the Metric 3 plan both
   assume a corpus module in this package for the shaderbench work; today
   `collect.py` covers only the copy-and-verify half.

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

### `collect.py` (second half) — "is it safe to uninstall this game?"

`check_game()` / `check_all()`, surfaced as `tcc collect --check`.

This exists because **uninstalling a game deletes its shadercache, and there is
no way to regenerate one** except reinstalling and replaying the same scenes.
The question "did I already save this?" has to be answerable *before* the disk
is freed. `tcc collect` could always copy; nothing could tell you what was still
at risk.

Every live cache file is compared against the collection in `data/foz/<slug>/`
and the game lands in one of six states. Three of them are safe —
`current` (everything copied), `archived` (no live cache left, the copy is all
there is), `no_cache` (never played) — and the command exits 1 if any game is
in the other three, so it can gate a script.

Two design decisions worth knowing:

- **A `manifest.json` is not a backup; the copied files are.** The index skips
  any manifest entry whose destination file is missing or the wrong size, so a
  manifest left behind by a deleted collection reads as "not collected" rather
  than as a false guarantee.
- **Identity is the path below `steamapps/`, not the absolute source path.**
  Manifests record absolute paths and those rot — the SataSSD library moved from
  `/media/methos/SataSSD` to `/mnt/SataSSD`, which made four games look entirely
  uncollected when they were byte-for-byte complete. Everything below
  `steamapps/` is assigned by Steam and survives a remount.

Size is the default comparison because the shallow check sweeps the whole
22.95 GB corpus; `--deep` re-hashes every live file instead. Verified agreeing
on 2026-08-03: `eldenring` and `solcesto` came out `current` under both,
`control` and `guardians-galaxy` `stale` under both.

### `corpus.py` — every `.foz` for a game, merged, provenance intact

Analysis used to run against **one** arbitrarily-chosen database. Measured
2026-08-03, that discards 52% of re6, 50% of remnant2 and 42% of helldivers2 by
size. In pipelines: cyberpunk2077's best single file holds 19,316 graphics
pipelines, the merge holds **23,365** (+21.0%); kh3 goes 83,283 → **99,493**
(+19.5%).

Merging is safe because Fossilize databases are content-addressed — merging N
files yields the **union** of their hashes, never the concatenation. Verified:
remnant2's two files hold 5,035 and 5,038 graphics pipelines and merge to 5,038,
not 10,073.

**The catch this module exists to solve.** Merging erases the file boundary that
distinguished `run_recorded` from `steam_precache` — the distinction the whole
evidence chain rests on. So the hash → provenance index is built *before* the
merge and persisted beside the corpus, and `analysis/stats.py` joins it back on
as a `provenance` column. You get the coverage of every file **and** keep the
ability to say "this pipeline was compiled on this machine". Verified on kh3:
83,288 run_recorded, 16,205 steam_precache, preserved through the merge.

`data/foz/` is the verified archive and is never mutated: the largest source is
*copied* to become the merge base, because `fossilize-merge-db` appends into its
first argument and starting from the largest file minimises I/O. Building is
per-game and explicit — the merged corpus roughly duplicates the archive on disk
(~20 GB for all 18 games).

### `resolve_foz()` in `foz.py` — the one selection rule

Which database a command analyses, with a documented precedence: explicit path →
`data/corpus/<game>/corpus.foz` → `<session>/foz/scene.foz` → the single file in
`after/` → the single import. **Never by mtime.** Two functions used to answer
this question independently, and one picked the newest file — so the same
session could be analysed against different databases by two commands, and
re-running months later could silently select different input.

`extract()` deliberately passes `use_corpus=False`: scene extraction scopes
*down* from one captured database and must not silently widen to the corpus.

## Ground rules a future change must not break

- Cache lookup goes through `launcher/steam.py`. Never glob `~/.local/share/Steam`
  directly: games live across several library folders and each game's cache is
  in *its own* library.
- Both layouts must keep working — new `fozpipelinesv6/steam_pipeline_cache.foz`
  and legacy `steamapprun_pipeline_cache.<hex>/steamapp_pipeline_cache.foz`.
- The `steamapprun` marker must survive any renaming during copy, or
  `run_created` becomes meaningless.

## Known problems, costs, and things I would flag

1. **`delta()` shells out to `fossilize-list` once per file per tag** — four tags
   across every before and after file, each a full pass over a possibly multi-GB
   database — and caches nothing. On the 22.95 GB corpus this dominates runtime,
   and re-running recomputes everything.
2. **`scene.foz` is a superset and must never be called "the scene".**
   `extract()` knowingly accepts prune's ~77–87 bonus pipelines because stats and
   disasm only need the requested hashes present. Fine for tooling, wrong in a
   sentence: filter the stats table by the requested hash list before writing
   anything about it.
3. **Manifests still record absolute source paths.** `check_game()` works around
   it by comparing the path below `steamapps/` (the SataSSD moving from
   `/media/…` to `/mnt/…` made four games look entirely uncollected), but
   `collect_game()` keeps writing mount-dependent paths, so any future consumer
   of `manifest.json → files[].source` inherits the same rot.
4. **`check_game()` cannot see content drift that preserves size.** The default
   comparison is size-only; a cache rewritten to exactly the same length with
   different contents reads as `current`. Run `--deep` before a bulk uninstall.
5. **Building a corpus roughly duplicates the archive on disk** — ~20 GB if built
   for all 18 games. It is per-game and explicit for that reason, but there is no
   `tcc corpus rm`, so cleanup is manual.
6. **`corpus.py` imports `_tool` from `foz.py`** — a private name across module
   boundaries. It works and it is one import, but it is the kind of coupling that
   should become a real export if a third caller appears.

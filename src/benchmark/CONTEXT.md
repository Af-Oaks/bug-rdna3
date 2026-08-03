# `benchmark/` — what the player actually sees

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/benchmark/` updates this file in
> the same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this package exists

**Metric 2: frames per second in a real game.** It is the least deterministic of
the three measurements and the only one that answers the question anyone outside
the thesis actually cares about. A compiler change that shrinks register usage
by 8% and moves no frames is a finding about compilers, not about games.

It is also the metric that needs a human. Menu-triggered benchmarks cannot be
automated away without per-game input scripting. The design accepts this
honestly: everything *around* the human step is automated and recorded, and the
human step is printed as explicit instructions read from the game's TOML.

## The one command

`tcc bench run --game X --profile P` is the whole capture flow:

```
session (new, or reuse --session)
  → foz snapshot "before"
  → arm the profile          (launcher/arm.py writes ~/.tcc/armed.{json,env})
  → launch                    (steam -applaunch; the wrapper applies the profile)
  → [human plays or triggers the in-game benchmark]
  → wait for the game process to disappear
  → foz snapshot "after" + delta
  → parse MangoHud CSVs → bench_summary.json
```

Every step is recorded into the session, so a run that goes wrong halfway is
still diagnosable, and the failure modes that are expected — no shader cache
yet, benchmark never triggered, MangoHud logging never toggled — degrade into a
printed note plus a session note rather than an exception.

`--no-wait` exists because "wait up to two hours for a process" is the wrong
behaviour when you are going to play for an hour and finish the collection by
hand; it prints the exact three commands to run afterwards.

## `game_bench.py` — the FPS parser worth understanding

MangoHud writes a CSV per run: two system-information rows, a column header row
containing `frametime`, then one row per frame in milliseconds. The parser finds
the header by scanning the first ten lines rather than assuming a fixed offset,
because the layout differs slightly across MangoHud 0.6 and 0.7.

**`PAUSE_FRAMETIME_MS = 200` is the correction that makes the numbers real.**
With `autostart_log=1`, logging begins when the Vulkan app comes up — which
means menus, load screens, and the pause between benchmark runs are all recorded
as single enormous "frames". One 57-minute frame destroys every mean, sum and
max while leaving percentiles intact, which is the worst kind of wrong: plausible
output. Frames slower than 200 ms (a 5 fps floor) are dropped before aggregating
and the count of dropped frames is reported, not hidden.

The summary reports average FPS, 1% and 0.1% lows, the frametime distribution,
and the system metadata MangoHud recorded. Proven on Metro EE: 52.8 fps average,
37.4 / 34.3 lows, 5,810 frames over 110 seconds.

## What this package is currently missing

This is one file, and ONGOING.md calls the missing part the critical path:

- **`shaderbench.py`** — Metric 3. Execute shaders pulled out of game `.foz`
  files as a deterministic GPU workload, so compiler changes can be timed on
  real game code without a game running. Feasibility is established (the `.foz`
  carries SPIR-V and layouts; 15–19 layouts cover 100k+ pipelines), the
  executor is roughly 850 lines of C++, and the SB-0 spike that could
  invalidate the whole idea has not been run yet.
- **`ledger.py`** — one row per (workload × compiler revision), joining all
  three metrics. This is where "a static win became a measured win" gets
  answered, and it is the reason the other two metrics are worth collecting.

## Ground rules a future change must not break

- Real gameplay launches keep the warm shader cache (`force_nocache=False`).
  Forcing `nocache` here would measure first-compile stutter, not steady-state
  frame rate. That is the opposite of the rule that governs `analysis/`.
- The human step stays visible. Instructions come from the game TOML and get
  printed; do not bury them.
- Every launch goes through the armed profile, never through per-experiment
  Steam launch options.

## Known problems, costs, and things I would flag

1. **Re-running a bench in the same session silently merges the runs.** `run()`
   checks whether *new* CSVs appeared since it started, but then calls
   `summarize()`, which parses **every** CSV in `bench/`. A second run in the
   same session produces a summary containing both runs as separate entries with
   nothing marking which was which, and the first run's numbers are re-reported
   as if fresh. Either summarize only the new files, or stamp each run.
2. **The 200 ms pause floor is a hardcoded constant, and it deletes data.** It
   is right today — no RDNA3 benchmark frame is slower than 5 fps. It is a
   silent data-loss mechanism the day a heavy 4K scene, a shader-compilation
   stutter, or a slower GPU crosses it, and the only evidence would be the
   `pause_frames_dropped` count that nobody reads. It belongs in the game TOML
   as a per-title value, and the summary should flag when the drop count is
   more than a fraction of a percent.
3. **`fps_1pct_low` is not the "1% low" most reviewers publish.** It is computed
   as `1000 / p99(frametime)` — the frametime at the 99th percentile. The
   commonly published figure is the *average* of the slowest 1% of frames. Both
   are defensible and they are not the same number; the thesis has to state
   which it uses or the comparison to published benchmarks is invalid.
4. **Nothing verifies the armed profile was actually applied.** `run()` checks
   afterwards whether the profile went unconsumed and prints a note, which is
   good — but if the game bypassed the wrapper, the FPS numbers were collected
   under the wrong driver and are still written to `bench_summary.json` as if
   valid. The armed-profile consumption state should land *in* the summary, so a
   later reader cannot mistake an uncontrolled run for a controlled one.
5. **`run()` returns a `Session` and communicates everything else by printing.**
   There is no structured return, so a caller that is not a human at a terminal
   has to go read the files to find out what happened.
6. **Every number here depends on an external tool whose version is not
   recorded.** MangoHud (`/usr/bin/mangohud`, distro-installed) produces the CSV
   this package parses, and the parser is explicitly tolerant of 0.6-versus-0.7
   layout differences — which means the layout matters. The summary records the
   system metadata MangoHud chose to write, but not the MangoHud version itself,
   so a future re-parse cannot tell which layout produced a given log.

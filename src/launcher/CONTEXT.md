# `launcher/` — forcing a driver into a game you do not control

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/launcher/` updates this file in
> the same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## The problem this package solves

To compare two compilers you must run the same game twice under two different
Mesa builds. But the game is launched by Steam, runs inside Proton, inside
pressure-vessel's container, and you cannot pass it environment variables from
the outside.

The obvious approach — edit the game's Steam launch options before each
experiment — fails on repeatability. It is manual, it is invisible to the
session record, and one forgotten edit invalidates a run without any sign that
it did.

## The armed-profile pattern

Steam launch options are set **once**, by hand, per game:

```
/path/to/repo/bin/tcc-launch.sh %command%
```

and never touched again. Per-experiment state goes into two files under `$HOME`:

- `~/.tcc/armed.json` — the canonical record: profile, driver, game, session,
  the full computed environment, TTL.
- `~/.tcc/armed.env` — the same environment flattened to `KEY=value` lines, so
  the shell wrapper needs no JSON parser inside the sandbox.

Two constraints shaped this. **It must live under `$HOME`**: pressure-vessel
mounts the home directory but does not reliably share `/tmp`, so an armed
profile in `/tmp` is invisible to the game. And it is **one-shot by default**:
the wrapper renames the files to `*.used` when it consumes them, so a profile
armed on Tuesday cannot silently contaminate Wednesday's run. The TTL is the
second, independent safety net — belt and braces, because a contaminated A/B
looks exactly like a real result.

## The files

### `arm.py` — write the armed profile

Computes the environment through `config.profile_env()` (never by hand), then
writes both files. Note the deliberate inversion versus `analysis/`: gameplay
launches pass `force_nocache=False`, keeping the warm shader cache, because
here we are measuring steady-state frame rate rather than compilation.

It also owns two conveniences that exist for specific real problems: MangoHud
config is generated with `autostart_log=1` for benchmark-type games, because the
`Shift_L+F2` hotkey is unreliable under Wayland and pressure-vessel; and
`TCC_EXE_OVERRIDE` / `TCC_EXE_MATCH` let the wrapper substitute a different
executable inside `%command%` — that is how Metro's separate benchmark binary
gets launched through the game's own Steam entry.

### `steam.py` — find things, start things, wait for things

`library_folders()` reads `libraryfolders.vdf`, because games here are spread
across several drives. `shadercache_foz()` resolves a game's caches across all
of them and handles both on-disk layouts. This is not incidental: resolving
caches by globbing `~/.local/share/Steam` hid every game installed on another
drive, and `tcc doctor` reported "no cache" for games that had one.

`launch()` sends Steam titles through `steam -applaunch` (which returns
immediately) and native titles directly through the wrapper, so both kinds share
the same armed-profile code path.

`wait_for_exit()` is honest about being best-effort. `steam -applaunch` gives
back no handle, but the game surfaces on the host as a
`reaper SteamLaunch AppId=<appid>` process even from inside the container, so it
polls `/proc` for that marker: wait for it to appear, then wait for it to go
away. It never raises on timeout — it returns what it observed and lets the
caller decide.

## Ground rules a future change must not break

- Armed state stays under `$HOME`. Never `/tmp`.
- One-shot stays the default. Sticky is opt-in and should stay uncomfortable.
- The environment comes from `config.profile_env()`. If a variable needs setting,
  it goes in a profile TOML, not in this package.
- `bin/tcc-launch.sh` is the other half of this contract. Changing the variable
  names here means changing the wrapper in the same commit.

## Known problems, costs, and things I would flag

1. **`bin/tcc-launch.sh` is untracked and gitignored.** The Python half of this
   contract is versioned; the shell half that actually consumes `armed.env`
   inside the sandbox is not in git and has no backup. It is tested, essential,
   and one `rm` away from gone. This is already an open question in ONGOING.md
   and it is the most serious item in this file.
2. **`_exe_match_for()` hardcodes game data in Python.** It is a dict containing
   exactly `{"metro-ee": "MetroExodus.exe"}`. Per-game facts belong in
   `config/games/*.toml` alongside the appid and the launch args; as written,
   every new benchmark executable means editing source code, and the config file
   for that game will not mention it.
3. **`armed.json` is never validated, and its schema has drifted.**
   `core/schemas/armed_profile.schema.json` describes a different structure from
   what `arm()` writes — it requires top-level `log_dir` and `mangohud`, which
   live inside the nested `tcc` object instead. Nothing catches this because
   nothing validates. Details in [../core/schemas/CONTEXT.md](../core/schemas/CONTEXT.md).
4. **`armed.env` drops keys without telling anyone.** Any variable whose name is
   not a plain shell identifier, or whose value contains a newline, is skipped
   with a bare `continue`. The JSON keeps the full record, so the two files
   disagree and the wrapper — which only reads the `.env` — never sees the
   dropped variable. A profile could specify an environment variable that
   silently does not reach the game.
5. **Process detection is a substring match on `/proc` cmdlines.** Anything whose
   command line contains `AppId=<appid>` counts as the game running, including a
   shell you happened to start with that string in an argument. It is documented
   as best-effort and it genuinely is; just do not build anything on top of it
   that assumes precision.
6. **`wait_for_exit()`'s timeouts do not mean what their names say.** The exit
   loop measures elapsed time from `started` — the beginning of the *appear*
   phase — so `exit_timeout_s` is a total budget, not an exit budget. A game
   that takes four minutes to appear gets four minutes less to run.
7. **`_proc_running()` walks all of `/proc` every three seconds.** Over a
   two-hour session that is roughly 2,400 full scans, each opening every
   process's `cmdline`. It is cheap enough not to matter and wasteful enough to
   mention; polling the appmanifest or a single known PID would be better if
   this ever runs alongside something performance-sensitive.

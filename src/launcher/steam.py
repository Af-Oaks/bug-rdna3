"""Steam interaction: library discovery, shadercache foz resolution,
launching games, and best-effort wait-for-exit.

Empirical notes (verified on this machine, 2026-07-23):

- Games live across MULTIPLE Steam library folders (SataSSD, external
  drives...), and each game's shadercache lives in ITS OWN library's
  steamapps/shadercache/<appid>/ -- NOT under ~/.local/share/Steam. Every
  cache lookup must therefore iterate libraryfolders.vdf.

- fozpipelinesv6 naming has TWO layouts in the wild here:
    new:    fozpipelinesv6/steam_pipeline_cache.foz            (Control, RE Requiem)
    legacy: fozpipelinesv6/steamapprun_pipeline_cache.<hex>/steamapp_pipeline_cache.foz
  (plus a replay_cache.<hex>.foz sibling we deliberately do NOT match --
  it is fossilize-replay's own cache, not game-created pipelines).
  The game TOMLs use the glob `**/*pipeline_cache*`; callers must keep
  only regular files (the legacy <hex> entry is a directory).

- `steam -applaunch <appid> [args...]` returns immediately; the game shows
  up on the host as a `reaper SteamLaunch AppId=<appid> -- ...` process
  even inside pressure-vessel, so wait_for_exit() polls /proc cmdlines for
  that marker. This is best-effort by design (plan §8 risk 5).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from core import config
from core.errors import TccError
from core.config import GameConfig

_VDF_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')


class SteamError(TccError):
    """Steam launch/lookup failures."""


def library_folders(cfg: config.TccConfig | None = None) -> list[Path]:
    """All Steam library roots (steam_root first, then libraryfolders.vdf
    entries), deduplicated, existing dirs only."""
    cfg = cfg or config.load_tcc_config()
    roots: list[Path] = [cfg.paths.steam_root]
    vdf = cfg.paths.steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        for match in _VDF_PATH_RE.finditer(vdf.read_text(encoding="utf-8", errors="replace")):
            roots.append(Path(match.group(1)))
    seen: set[Path] = set()
    result = []
    for root in roots:
        root = root.expanduser()
        if root not in seen and (root / "steamapps").is_dir():
            seen.add(root)
            result.append(root)
    return result


def find_app_library(appid: int, cfg: config.TccConfig | None = None) -> Path | None:
    """The library root whose steamapps/ contains appmanifest_<appid>.acf."""
    for root in library_folders(cfg):
        if (root / "steamapps" / f"appmanifest_{appid}.acf").is_file():
            return root
    return None


def shadercache_foz(game_cfg: GameConfig, cfg: config.TccConfig | None = None) -> list[Path]:
    """All foz cache files for a game, searched across every library folder
    (regular files only -- legacy caches nest the .foz inside a hex-named
    directory that the glob also matches)."""
    if game_cfg.game.appid is None or not game_cfg.foz.cache_glob:
        return []
    pattern = game_cfg.foz.cache_glob.format(appid=game_cfg.game.appid)
    matches: list[Path] = []
    for root in library_folders(cfg):
        matches.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(matches))


# ---------------------------------------------------------------------------
# launch / wait
# ---------------------------------------------------------------------------


def launch(game_cfg: GameConfig, extra_args: list[str] | None = None,
           cfg: config.TccConfig | None = None) -> subprocess.Popen | None:
    """Start a game. Steam titles go through `steam -applaunch` (returns
    immediately; the armed wrapper set once in the game's launch options
    does the env work). native-cli titles run directly THROUGH the wrapper
    so both kinds share the exact same armed-profile code path.

    Returns the Popen for native-cli launches (caller can .wait() on it);
    None for Steam launches (use wait_for_exit(appid) instead).
    """
    cfg = cfg or config.load_tcc_config()
    args = list(game_cfg.benchmark.launch_args) + list(extra_args or [])

    if game_cfg.game.kind == "steam":
        if game_cfg.game.appid is None:
            raise SteamError(f"{game_cfg.game.slug}: kind=steam but no appid configured")
        steam_bin = shutil.which("steam")
        if not steam_bin:
            raise SteamError("`steam` not found on PATH")
        argv = [steam_bin, "-applaunch", str(game_cfg.game.appid), *args]
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return None

    if game_cfg.game.kind == "native-cli":
        exe = game_cfg.game.exe_path or game_cfg.game.slug
        wrapper = cfg.paths.wrapper
        argv = ([str(wrapper)] if wrapper.is_file() else []) + [exe, *args]
        return subprocess.Popen(argv)

    raise SteamError(
        f"{game_cfg.game.slug}: kind={game_cfg.game.kind!r} has no automated launch path; "
        "start it manually (see the game TOML instructions)."
    )


def _proc_running(marker: bytes) -> bool:
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/cmdline", "rb") as fh:
                if marker in fh.read():
                    return True
        except OSError:
            continue  # process vanished / permission
    return False


def wait_for_exit(appid: int, appear_timeout_s: int = 300,
                  exit_timeout_s: int = 7200, poll_s: float = 3.0) -> dict:
    """Best-effort: wait for the `AppId=<appid>` reaper process to appear,
    then to disappear. Returns {"appeared": bool, "exited": bool,
    "elapsed_s": float}. Never raises on timeout -- callers decide."""
    marker = f"AppId={appid}".encode()
    started = time.monotonic()

    appeared = False
    while time.monotonic() - started < appear_timeout_s:
        if _proc_running(marker):
            appeared = True
            break
        time.sleep(poll_s)

    exited = False
    if appeared:
        while time.monotonic() - started < exit_timeout_s:
            if not _proc_running(marker):
                exited = True
                break
            time.sleep(poll_s)

    return {"appeared": appeared, "exited": exited,
            "elapsed_s": round(time.monotonic() - started, 1)}

"""Armed-profile launches (Phase 3).

`tcc arm --profile X` writes BOTH:
  ~/.tcc/armed.json  -- canonical record (profile, game, session, env, ttl)
  ~/.tcc/armed.env   -- flat KEY=value lines so bin/tcc-launch.sh needs zero
                        JSON parsing inside pressure-vessel.

Both files MUST live under $HOME: Steam's pressure-vessel sandbox mounts
$HOME but does not reliably share /tmp. One-shot by default: the wrapper
renames the files to *.used on consumption so a forgotten armed profile can
never contaminate the next day's launch (TTL is the second safety net).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from core import config, paths, util
from core.session import Session

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_TTL_MIN = 240


class ArmError(Exception):
    pass


def armed_env_path() -> Path:
    return paths.armed_profile_path().with_suffix(".env")


def _default_mangohud_config(bench_dir: Path, autostart: bool) -> str:
    # Every-frame CSV logging into the session's bench/ dir. autostart=True
    # (benchmark-type games) starts logging 1s after the Vulkan app comes up
    # -- no hotkey needed, which matters because Shift_L+F2 capture is
    # unreliable under Wayland/pressure-vessel. Manual scenes keep
    # toggle-only so hour-long play sessions aren't logged wall-to-wall.
    base = f"output_folder={bench_dir},log_interval=0,toggle_logging=Shift_L+F2"
    return f"{base},autostart_log=1" if autostart else base


def arm(
    profile_name: str,
    session: Session | None = None,
    game: str | None = None,
    ttl_min: int = DEFAULT_TTL_MIN,
    sticky: bool = False,
    exe_override: str | None = None,
    exe_match: str | None = None,
    extra_env: dict[str, str] | None = None,
    mangohud_autostart: bool = False,
) -> dict:
    """Compute the profile environment and write armed.json + armed.env.
    Returns the canonical armed payload (what went into armed.json)."""
    cfg = config.load_tcc_config()
    profile = config.load_profile_config(profile_name)

    game_slug = game or (session.game if session else None)
    game_cfg = config.load_game_config(game_slug) if game_slug else None
    appid = game_cfg.game.appid if game_cfg else None

    if session is not None:
        session_dir = session.root
        log_dir = session.subdir("logs")
        bench_dir = session.subdir("bench")
    else:
        if profile.shader_cache_dir == "session":
            raise ArmError(
                f"profile {profile_name!r} uses shader_cache_dir=\"session\"; "
                "pass --session so the isolated cache has somewhere to live."
            )
        session_dir = Path.home() / ".tcc"
        log_dir = session_dir / "logs"
        bench_dir = session_dir / "bench"
    util.ensure_dir(log_dir)

    # Real gameplay/bench launches keep the warm cache unless the profile
    # itself says otherwise -- force_nocache is for stats/disasm replays.
    env = config.profile_env(profile, session_dir, force_nocache=False, cfg=cfg)

    if profile.mangohud:
        util.ensure_dir(bench_dir)
        env.setdefault("MANGOHUD_CONFIG", _default_mangohud_config(bench_dir, mangohud_autostart))
        env.setdefault("MANGOHUD", "1")  # implicit-layer fallback path

    if extra_env:
        env.update(extra_env)

    now = int(time.time())
    tcc_vars: dict[str, str] = {
        "TCC_PROFILE": profile.name,
        "TCC_ONE_SHOT": "0" if sticky else "1",
        "TCC_EXPIRES_EPOCH": str(now + ttl_min * 60),
        "TCC_LOG_DIR": str(log_dir),
        "TCC_MANGOHUD": "1" if profile.mangohud else "0",
    }
    if appid is not None:
        tcc_vars["TCC_APPID"] = str(appid)
    if session is not None:
        tcc_vars["TCC_SESSION"] = session.session_id
    if exe_override:
        match = exe_match or (_exe_match_for(game_cfg) if game_cfg else "")
        if not match:
            raise ArmError(
                "--exe-override needs the original exe basename to replace in "
                "%command%; pass --exe-match (e.g. --exe-match MetroExodus.exe)."
            )
        tcc_vars["TCC_EXE_OVERRIDE"] = str(Path(exe_override))
        tcc_vars["TCC_EXE_MATCH"] = match

    payload = {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "profile": profile.name,
        "driver": profile.driver,
        "game": game_slug,
        "appid": appid,
        "session_id": session.session_id if session else None,
        "one_shot": not sticky,
        "expires_epoch": now + ttl_min * 60,
        "env": env,
        "tcc": tcc_vars,
    }

    json_path = paths.armed_profile_path()
    util.ensure_dir(json_path.parent)
    util.write_json(json_path, payload)

    lines = []
    for key, value in {**env, **tcc_vars}.items():
        if not _KEY_RE.match(key) or "\n" in str(value):
            continue  # json keeps the full record; the flat file stays shell-safe
        lines.append(f"{key}={value}")
    armed_env_path().write_text("\n".join(lines) + "\n", encoding="utf-8")

    if session is not None:
        session.use_profile(profile.name)
        session.record_step("arm", ["tcc", "arm", "--profile", profile.name], 0,
                            armed_env=env, tcc_vars=tcc_vars)
    return payload


def _exe_match_for(game_cfg: config.GameConfig) -> str:
    """Basename the wrapper should look for in %command% when substituting
    an exe override. For Proton games that is the game's main .exe; default
    to the last path-looking arg at wrapper runtime if we can't know it, so
    here we just fall back to a per-game map when needed."""
    known = {
        "metro-ee": "MetroExodus.exe",
    }
    return known.get(game_cfg.game.slug, "")


def show() -> dict | None:
    json_path = paths.armed_profile_path()
    if not json_path.is_file():
        return None
    payload = util.read_json(json_path)
    payload["stale"] = int(time.time()) > int(payload.get("expires_epoch", 0))
    payload["env_file_present"] = armed_env_path().is_file()
    return payload


def disarm() -> bool:
    """Remove armed files. Returns True if anything was removed."""
    removed = False
    for path in (paths.armed_profile_path(), armed_env_path()):
        if path.is_file():
            path.unlink()
            removed = True
    return removed

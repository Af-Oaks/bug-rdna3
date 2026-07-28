"""Canonical filesystem path resolution.

Every function here is pure (no config/TOML loading, no side effects beyond
stat calls) so that config.py and every other module can depend on it
without risking a circular import.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Walk up from this file looking for pyproject.toml."""
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        f"Could not locate repo root (no pyproject.toml found above {here}). "
        "Is tcc installed outside its source checkout?"
    )


def data_dir() -> Path:
    return repo_root() / "data"


def session_root(game: str, session_id: str) -> Path:
    return data_dir() / "sessions" / game / session_id


def steam_root() -> Path:
    """Default Steam library root. Override with $TCC_STEAM_ROOT for testing."""
    override = os.environ.get("TCC_STEAM_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "Steam"


def armed_profile_path() -> Path:
    """Canonical armed-profile location. MUST live under $HOME: pressure-vessel
    (Steam's sandbox) mounts $HOME but not /tmp, so /tmp is unsafe here."""
    return Path.home() / ".tcc" / "armed.json"

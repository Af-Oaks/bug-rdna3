"""Minimal validation helpers to keep dependencies low."""

from __future__ import annotations

from pathlib import Path


def require_keys(payload: dict, required_keys: list[str], label: str) -> None:
    missing = [key for key in required_keys if key not in payload]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise ValueError(f"{label} is missing required keys: {missing_csv}")


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")

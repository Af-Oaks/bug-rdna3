"""Thin wrapper around the legacy top-level extract.py helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .constants import REPO_ROOT


def run_legacy_extract(log_path: Path, output_json: Path, seed: int = 42) -> dict:
    extract_script = REPO_ROOT / "extract.py"
    if not extract_script.exists():
        return {
            "status": "missing",
            "script_path": str(extract_script),
            "message": "Legacy extract.py is not present in the repository root.",
        }

    spec = importlib.util.spec_from_file_location("legacy_extract", extract_script)
    if spec is None or spec.loader is None:
        return {
            "status": "error",
            "script_path": str(extract_script),
            "message": "Unable to load extract.py module specification.",
        }

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.extract_deterministic_shaders(str(log_path), str(output_json), seed=seed)
    return {
        "status": "ok",
        "script_path": str(extract_script),
        "log_path": str(log_path),
        "output_json": str(output_json),
        "seed": seed,
    }

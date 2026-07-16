"""Tool resolution with local-first preference and explicit reporting."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .constants import TOOL_CANDIDATES


def resolve_tool(tool_name: str) -> dict:
    searched = []
    for candidate in TOOL_CANDIDATES.get(tool_name, []):
        searched.append(str(candidate))
        if candidate.exists() and os.access(candidate, os.X_OK):
            location = "local" if "analysis/tools/local" in str(candidate) else "vendored"
            return {
                "tool": tool_name,
                "path": str(candidate.resolve()),
                "status": location,
                "searched": searched,
            }

    system_path = shutil.which(tool_name)
    if system_path:
        return {
            "tool": tool_name,
            "path": str(Path(system_path).resolve()),
            "status": "system",
            "searched": searched,
        }

    return {
        "tool": tool_name,
        "path": None,
        "status": "missing",
        "searched": searched,
    }


def resolve_many(*tool_names: str) -> dict[str, dict]:
    return {tool_name: resolve_tool(tool_name) for tool_name in tool_names}


def format_tool_report(report: dict) -> str:
    path = report.get("path") or "<not found>"
    return f"{report['tool']}: {report['status']} -> {path}"

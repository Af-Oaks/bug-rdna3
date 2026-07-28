"""Tool resolution and `tcc doctor` environment checks.

Resolution order: build/install/bin (local, stock Mesa build) -> tools/**
(vendored, recursive+executable) -> PATH (system). Anything not found in any
of those is "missing".
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import config

FOSSILIZE_TOOLS = (
    "fossilize-list",
    "fossilize-prune",
    "fossilize-disasm",
    "fossilize-replay",
    "fossilize-synth",
)
REQUIRED_SYSTEM_TOOLS = ("glslangValidator", "spirv-dis", "steam")
OPTIONAL_TOOLS_REMEDY = {
    "mangohud": "apt install mangohud (Phase 6: bench.py needs it for FPS/frametime capture)",
    "renderdoccmd": "apt install renderdoc (Phase 6: RenderDoc capture backend B)",
    "qrenderdoc": "apt install renderdoc (Phase 6: RenderDoc capture backend B)",
    "rga": "download the AMD RGA Linux tarball into tools/rga/ (Phase 4)",
    "vkmark": "apt install vkmark (Phase 6: synthetic benchmark cohort)",
    "vkpeak": "build vkpeak from source into tools/ (Phase 6: synthetic benchmark cohort)",
}


@dataclass
class ToolInfo:
    name: str
    path: Path | None
    origin: str  # local | vendored | system | missing


@dataclass
class Check:
    name: str
    status: str  # ok | warn | missing
    detail: str
    remedy: str | None = None


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve(tool: str, cfg: config.TccConfig | None = None) -> ToolInfo:
    cfg = cfg or config.load_tcc_config()

    local = cfg.paths.mesa_stock / "bin" / tool
    if _is_executable(local):
        return ToolInfo(tool, local, "local")

    if cfg.paths.tools_dir.is_dir():
        for candidate in sorted(cfg.paths.tools_dir.rglob(tool)):
            if _is_executable(candidate):
                return ToolInfo(tool, candidate, "vendored")

    which = shutil.which(tool)
    if which:
        return ToolInfo(tool, Path(which), "system")

    return ToolInfo(tool, None, "missing")


def _check_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _foz_cache_hits(cfg: config.TccConfig, game_cfg: config.GameConfig) -> int:
    """Resolve across ALL Steam library folders, not just steam_root -- the
    shadercache lives in the library the game is installed in, and games here
    are spread over several drives. Must match what foz.snapshot() actually
    finds, or doctor reports "no cache" for games that have one."""
    from launcher import steam as steam_mod

    return len(steam_mod.shadercache_foz(game_cfg))


def doctor() -> list[Check]:
    checks: list[Check] = []
    cfg = config.load_tcc_config()

    for tool in FOSSILIZE_TOOLS:
        info = resolve(tool, cfg)
        if info.origin == "missing":
            checks.append(
                Check(
                    tool,
                    "missing",
                    "not found in build/install/bin, tools/, or PATH",
                    "build Fossilize (see scripts/setup_env.sh); expected under build/install/bin",
                )
            )
        else:
            checks.append(Check(tool, "ok", f"{info.origin}: {info.path}"))

    for tool in REQUIRED_SYSTEM_TOOLS:
        info = resolve(tool, cfg)
        if info.origin == "missing":
            checks.append(Check(tool, "missing", "not found", f"install {tool} (distro package)"))
        else:
            checks.append(Check(tool, "ok", f"{info.origin}: {info.path}"))

    for tool, remedy in OPTIONAL_TOOLS_REMEDY.items():
        info = resolve(tool, cfg)
        if info.origin == "missing":
            checks.append(Check(tool, "warn", "not found (optional for Phase 1)", remedy))
        else:
            checks.append(Check(tool, "ok", f"{info.origin}: {info.path}"))

    for label, mesa_dir in (
        ("mesa stock ICD", cfg.paths.mesa_stock),
        ("mesa custom ICD", cfg.paths.mesa_custom),
    ):
        icd_dir = mesa_dir / "share" / "vulkan" / "icd.d"
        jsons = sorted(icd_dir.glob("*.json")) if icd_dir.is_dir() else []
        if jsons:
            checks.append(Check(label, "ok", f"{len(jsons)} icd json(s) in {icd_dir}"))
        else:
            checks.append(
                Check(
                    label,
                    "missing",
                    f"no icd json under {icd_dir}",
                    f"build mesa into {mesa_dir} (scripts/setup_env.sh / scripts/build_custom_aco.sh)",
                )
            )

    tcc_home = Path.home() / ".tcc"
    writable = _check_writable(tcc_home)
    checks.append(
        Check(
            "~/.tcc writable",
            "ok" if writable else "missing",
            str(tcc_home),
            None if writable else "mkdir -p ~/.tcc and ensure it is writable (needed by arm.py, Phase 3)",
        )
    )

    wrapper = cfg.paths.wrapper
    if _is_executable(wrapper):
        checks.append(Check("bin/tcc-launch.sh", "ok", str(wrapper)))
    else:
        checks.append(
            Check(
                "bin/tcc-launch.sh",
                "warn",
                "missing or not executable",
                "create bin/tcc-launch.sh (Phase 3)",
            )
        )

    for slug in config.list_games():
        try:
            game_cfg = config.load_game_config(slug)
        except config.ConfigError as exc:
            checks.append(Check(f"foz cache: {slug}", "warn", f"could not load game config: {exc}"))
            continue
        if game_cfg.game.appid is None or not game_cfg.foz.cache_glob:
            continue  # native-cli / non-steam titles have no Steam shadercache to check
        hits = _foz_cache_hits(cfg, game_cfg)
        if hits:
            checks.append(Check(f"foz cache: {slug}", "ok", f"{hits} file(s) match cache glob"))
        else:
            checks.append(
                Check(
                    f"foz cache: {slug}",
                    "warn",
                    "no shader cache files found yet",
                    "launch and play the game once to populate the shader cache",
                )
            )

    for module, required in (("jsonschema", True), ("pandas", False)):
        try:
            __import__(module)
            checks.append(Check(f"python: {module}", "ok", "importable"))
        except ImportError:
            checks.append(
                Check(
                    f"python: {module}",
                    "missing" if required else "warn",
                    "not importable",
                    "pip install -e . (adds it via pyproject dependencies)",
                )
            )

    return checks

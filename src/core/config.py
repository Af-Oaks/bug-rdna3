"""TOML config loading: config/tcc.toml, config/games/<slug>.toml, config/profiles/<name>.toml.

profile_env() is THE single place environment variables get computed for
Vulkan invocations. All A/B-sensitive callers (stats, foz disasm, shaderlab)
must go through it so nocache + isolated shader cache are never forgotten.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

CONFIG_DIR_NAME = "config"


class ConfigError(Exception):
    """Missing or malformed configuration."""


def config_dir() -> Path:
    return paths.repo_root() / CONFIG_DIR_NAME


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _resolve_repo_path(value: str) -> Path:
    """Relative paths in tcc.toml are relative to the repo root; ~ and
    absolute paths are honored as-is."""
    expanded = Path(value).expanduser()
    if expanded.is_absolute():
        return expanded
    return paths.repo_root() / expanded


# ---------------------------------------------------------------------------
# config/tcc.toml
# ---------------------------------------------------------------------------


@dataclass
class Paths:
    data_dir: Path
    mesa_stock: Path
    mesa_custom: Path
    tools_dir: Path
    steam_root: Path
    armed_profile: Path
    wrapper: Path


@dataclass
class Defaults:
    gpu_arch: str
    replay_threads: int
    replay_timeout_s: int
    top_n_offenders: int


@dataclass
class TccConfig:
    paths: Paths
    defaults: Defaults


def load_tcc_config() -> TccConfig:
    raw = _load_toml(config_dir() / "tcc.toml")
    p = raw.get("paths", {})
    d = raw.get("defaults", {})
    return TccConfig(
        paths=Paths(
            data_dir=_resolve_repo_path(p.get("data_dir", "data")),
            mesa_stock=_resolve_repo_path(p.get("mesa_stock", "build/install")),
            mesa_custom=_resolve_repo_path(p.get("mesa_custom", "build/install_custom")),
            tools_dir=_resolve_repo_path(p.get("tools_dir", "tools")),
            steam_root=Path(p.get("steam_root", "~/.local/share/Steam")).expanduser(),
            armed_profile=Path(p.get("armed_profile", "~/.tcc/armed.json")).expanduser(),
            wrapper=_resolve_repo_path(p.get("wrapper", "bin/tcc-launch.sh")),
        ),
        defaults=Defaults(
            gpu_arch=d.get("gpu_arch", "gfx1101"),
            replay_threads=d.get("replay_threads", 4),
            replay_timeout_s=d.get("replay_timeout_s", 30),
            top_n_offenders=d.get("top_n_offenders", 25),
        ),
    )


# ---------------------------------------------------------------------------
# config/games/<slug>.toml
# ---------------------------------------------------------------------------


@dataclass
class GameSection:
    slug: str
    name: str
    kind: str  # steam | non-steam-proton | native-cli
    appid: int | None
    runtime: str
    api: str  # vulkan | vkd3d | dxvk
    engine: str
    cohort: str  # high-gain | low-gain | synthetic | reference
    exe_path: str | None = None  # only meaningful for non-steam-proton


@dataclass
class BenchmarkSection:
    type: str  # builtin | standalone | manual-scene | cli
    trigger: str  # menu | autostart | cli-args
    launch_args: list[str] = field(default_factory=list)
    duration_hint_s: int | None = None
    instructions: str = ""


@dataclass
class FozSection:
    cache_glob: str = ""  # relative to steam_root, "{appid}" placeholder


@dataclass
class Scene:
    id: str
    kind: str  # benchmark | manual
    protocol_doc: str = ""


@dataclass
class GameConfig:
    game: GameSection
    benchmark: BenchmarkSection
    foz: FozSection
    scenes: list[Scene]


def games_dir() -> Path:
    return config_dir() / "games"


def list_games() -> list[str]:
    if not games_dir().is_dir():
        return []
    return sorted(p.stem for p in games_dir().glob("*.toml"))


def load_game_config(slug: str) -> GameConfig:
    path = games_dir() / f"{slug}.toml"
    raw = _load_toml(path)
    try:
        g = raw["game"]
        b = raw["benchmark"]
    except KeyError as exc:
        raise ConfigError(f"{path}: missing required section {exc}") from exc
    f = raw.get("foz", {})
    scenes = [
        Scene(id=s["id"], kind=s["kind"], protocol_doc=s.get("protocol_doc", ""))
        for s in raw.get("scenes", [])
    ]
    return GameConfig(
        game=GameSection(
            slug=g["slug"],
            name=g["name"],
            kind=g["kind"],
            appid=g.get("appid"),
            runtime=g.get("runtime", ""),
            api=g.get("api", ""),
            engine=g.get("engine", ""),
            cohort=g.get("cohort", ""),
            exe_path=g.get("exe_path"),
        ),
        benchmark=BenchmarkSection(
            type=b["type"],
            trigger=b["trigger"],
            launch_args=list(b.get("launch_args", [])),
            duration_hint_s=b.get("duration_hint_s"),
            instructions=b.get("instructions", ""),
        ),
        foz=FozSection(cache_glob=f.get("cache_glob", "")),
        scenes=scenes,
    )


# ---------------------------------------------------------------------------
# config/profiles/<name>.toml
# ---------------------------------------------------------------------------


@dataclass
class ProfileConfig:
    name: str
    driver: str  # system | stock | custom
    radv_debug: list[str] = field(default_factory=list)
    radv_perftest: list[str] = field(default_factory=list)
    mangohud: bool = False
    renderdoc: bool = False
    sqtt: bool = False
    shader_cache_dir: str = "default"  # "session" | "default"
    env: dict[str, str] = field(default_factory=dict)


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def list_profiles() -> list[str]:
    if not profiles_dir().is_dir():
        return []
    return sorted(p.stem for p in profiles_dir().glob("*.toml"))


def load_profile_config(name: str) -> ProfileConfig:
    path = profiles_dir() / f"{name}.toml"
    raw = _load_toml(path)
    try:
        p = raw["profile"]
    except KeyError as exc:
        raise ConfigError(f"{path}: missing [profile] section") from exc
    return ProfileConfig(
        name=p.get("name", name),
        driver=p["driver"],
        radv_debug=list(p.get("radv_debug", [])),
        radv_perftest=list(p.get("radv_perftest", [])),
        mangohud=p.get("mangohud", False),
        renderdoc=p.get("renderdoc", False),
        sqtt=p.get("sqtt", False),
        shader_cache_dir=p.get("shader_cache_dir", "default"),
        env=dict(raw.get("env", {})),
    )


# ---------------------------------------------------------------------------
# ICD resolution + the one place env vars get computed
# ---------------------------------------------------------------------------


def resolve_icd(driver: str, cfg: TccConfig | None = None) -> Path | None:
    """Absolute ICD json path for stock/custom, verified to exist. None means
    "use whatever Vulkan loader picks by default" (driver == system)."""
    if driver == "system":
        return None
    cfg = cfg or load_tcc_config()
    if driver == "stock":
        mesa_dir = cfg.paths.mesa_stock
    elif driver == "custom":
        mesa_dir = cfg.paths.mesa_custom
    else:
        raise ConfigError(f"Unknown driver {driver!r}; expected system|stock|custom")

    icd_dir = mesa_dir / "share" / "vulkan" / "icd.d"
    matches = sorted(icd_dir.glob("*.json")) if icd_dir.is_dir() else []
    if not matches:
        raise ConfigError(
            f"No Vulkan ICD json found for driver={driver!r} under {icd_dir}. "
            f"Build Mesa into {mesa_dir} first "
            "(see scripts/setup_env.sh / scripts/build_custom_aco.sh)."
        )
    return matches[0]


def profile_env(
    profile: ProfileConfig,
    session_dir: Path,
    force_nocache: bool = True,
    cfg: TccConfig | None = None,
) -> dict[str, str]:
    """Compute the full environment for a Vulkan invocation under `profile`.

    force_nocache defaults True because most callers (stats, foz disasm,
    shaderlab) are A/B-sensitive and pipeline-cache reuse would silently
    corrupt a comparison. Real gameplay/benchmark launches should pass
    force_nocache=False explicitly (Phase 3/6 concern).
    """
    env: dict[str, str] = {}

    icd = resolve_icd(profile.driver, cfg)
    if icd is not None:
        env["VK_ICD_FILENAMES"] = str(icd)

    radv_debug = list(profile.radv_debug)
    if force_nocache and "nocache" not in radv_debug:
        radv_debug.append("nocache")
    if radv_debug:
        env["RADV_DEBUG"] = ",".join(radv_debug)

    if profile.radv_perftest:
        env["RADV_PERFTEST"] = ",".join(profile.radv_perftest)

    if profile.shader_cache_dir == "session":
        cache_dir = Path(session_dir) / "shader_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        env["MESA_SHADER_CACHE_DIR"] = str(cache_dir)

    if profile.renderdoc:
        env["ENABLE_VULKAN_RENDERDOC_CAPTURE"] = "1"

    if profile.sqtt:
        env["RADV_THREAD_TRACE_TRIGGER"] = str(Path(session_dir) / "sqtt.trigger")

    env.update(profile.env)
    return env

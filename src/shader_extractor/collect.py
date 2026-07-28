"""Collect recorded pipeline caches out of the Steam shadercache into data/foz/<slug>/.

Steam's Fossilize layer records every pipeline a game creates, with no help
from us -- playing the game is the whole capture step. This module copies
those databases somewhere durable (they live on the game's own drive and are
wiped whenever Steam decides to), verifies them, and records where each one
came from.

Three kinds of file live in a shadercache and they are NOT interchangeable:

  run_recorded   steamapprun_* -- recorded by launches on THIS machine.
                 The only class that proves the local GPU/driver compiled it.
  steam_precache steamapp_pipeline_cache.foz / steam_pipeline_cache.foz --
                 may be Steam's downloaded community cache. Usable shader
                 material, but never evidence of what this machine ran.
  whitelist      steam_pipeline_cache_whitelist.foz -- Valve's curated set.

Everything else in a shadercache is deliberately skipped: mesa_shader_cache_sf
(RADV's own compiled-blob cache, not pipeline create-infos), radv_builtin_shaders,
replay_cache.*, and transcoded_video.foz (PRAGMATA ships 1.2GB of *video* there).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from core import config, provenance, util
from launcher import steam


class CollectError(RuntimeError):
    pass


@dataclass
class CollectedFile:
    dest_name: str
    source: str
    library: str
    size: int
    sha256: str
    kind: str  # run_recorded | steam_precache | whitelist


def classify(path: Path) -> str:
    if "whitelist" in path.name:
        return "whitelist"
    if "steamapprun" in path.name or "steamapprun" in path.parent.name:
        return "run_recorded"
    return "steam_precache"


def _dest_name(src: Path, taken: set[str]) -> str:
    """Flatten the nested layout without losing the run-directory name --
    steamapprun_<hex>/steamapp_pipeline_cache.foz and a top-level
    steamapp_pipeline_cache.foz are different databases with the same basename."""
    name = src.name if src.parent.name == "fozpipelinesv6" else f"{src.parent.name}__{src.name}"
    if name in taken:  # same basename from another library
        name = f"{src.parent.parent.name}__{name}"
    return name


def collect_game(slug: str, dest_root: Path | None = None, skip_whitelist: bool = False) -> dict:
    """Copy every pipeline database for one game into data/foz/<slug>/.
    Returns a manifest dict; also written as <dest>/manifest.json."""
    game_cfg = config.load_game_config(slug)
    if game_cfg.game.appid is None:
        raise CollectError(f"{slug}: no appid (not a Steam title)")

    sources = steam.shadercache_foz(game_cfg)
    if not sources:
        raise CollectError(f"{slug}: no pipeline cache found -- has the game been played?")

    dest_dir = util.ensure_dir((dest_root or (config.load_tcc_config().paths.data_dir / "foz")) / slug)

    files: list[CollectedFile] = []
    taken: set[str] = set()
    for src in sources:
        kind = classify(src)
        if skip_whitelist and kind == "whitelist":
            continue
        name = _dest_name(src, taken)
        taken.add(name)
        dest = dest_dir / name

        # Skip an identical file already collected (re-running must be cheap).
        src_sha = provenance.sha256_file(src)
        if dest.exists() and dest.stat().st_size == src.stat().st_size:
            if provenance.sha256_file(dest) == src_sha:
                files.append(CollectedFile(name, str(src), _library_of(src), src.stat().st_size, src_sha, kind))
                continue

        shutil.copy2(src, dest)
        dest_sha = provenance.sha256_file(dest)
        if dest_sha != src_sha:
            raise CollectError(f"{slug}: checksum mismatch after copying {src} -> {dest}")
        files.append(CollectedFile(name, str(src), _library_of(src), dest.stat().st_size, dest_sha, kind))

    manifest = {
        "slug": slug,
        "appid": game_cfg.game.appid,
        "name": game_cfg.game.name,
        "total_bytes": sum(f.size for f in files),
        "counts": {
            k: sum(1 for f in files if f.kind == k)
            for k in ("run_recorded", "steam_precache", "whitelist")
        },
        "files": [asdict(f) for f in files],
    }
    util.write_json(dest_dir / "manifest.json", manifest)
    return manifest


def _library_of(path: Path) -> str:
    for part in path.parents:
        if (part / "steamapps").is_dir():
            return str(part)
    return str(path.parent)


def collect_all(slugs: list[str] | None = None, skip_whitelist: bool = False) -> dict:
    """Collect every configured Steam game that has a cache. Games with no
    cache are reported, not raised -- a partial collection is still useful."""
    if slugs is None:
        slugs = sorted(p.stem for p in config.games_dir().glob("*.toml"))

    collected, skipped = {}, {}
    for slug in slugs:
        try:
            collected[slug] = collect_game(slug, skip_whitelist=skip_whitelist)
        except CollectError as exc:
            skipped[slug] = str(exc)
    return {"collected": collected, "skipped": skipped}

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
from core.errors import TccError
from launcher import steam


class CollectError(TccError):
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


def flat_name(src: Path, taken: set[str]) -> str:
    """Flatten the nested cache layout into one filename without losing the
    run-directory name.

    steamapprun_<hex>/steamapp_pipeline_cache.foz and a top-level
    steamapp_pipeline_cache.foz are different databases with the same basename,
    so the parent directory is prefixed whenever it is not "fozpipelinesv6",
    and the grandparent is added on collision (same basename from another
    library).

    THIS IS LOAD-BEARING: foz.delta()'s run_created identifies run-recorded
    caches by testing for "steamapprun" in the filename, which only works
    because this rule preserves it. Both snapshot() and collect_game() call
    this one function so a change cannot reach one path and miss the other."""
    name = src.name if src.parent.name == "fozpipelinesv6" else f"{src.parent.name}__{src.name}"
    if name in taken:
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
        name = flat_name(src, taken)
        taken.add(name)
        dest = dest_dir / name

        # Re-running must be cheap: size+mtime rules out most work before any
        # hashing. Only when they match do we pay for a checksum, and then only
        # of the destination (on the fast drive) plus the source once.
        src_stat = src.stat()
        if dest.exists() and dest.stat().st_size == src_stat.st_size:
            src_sha = provenance.sha256_file(src)
            if provenance.sha256_file(dest) == src_sha:
                files.append(CollectedFile(name, str(src), _library_of(src), src_stat.st_size, src_sha, kind))
                continue
        else:
            src_sha = provenance.sha256_file(src)

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


# ---------------------------------------------------------------------------
# check: is it safe to uninstall this game?
# ---------------------------------------------------------------------------
#
# Uninstalling a game deletes its shadercache, and a shadercache is the only
# place a pipeline database ever exists -- there is no way to regenerate one
# except by reinstalling and replaying the same scenes. So "did I already save
# this?" has to be answerable BEFORE the disk is freed, not after.
#
# A manifest.json is not a backup. The copied files are. Every check therefore
# verifies the destination file is still on disk at the recorded size, not just
# that the manifest mentions it.

#: Statuses where nothing would be lost by removing the game right now.
SAFE_STATUSES = ("current", "archived", "no_cache")


@dataclass
class CacheStatus:
    slug: str
    installed: bool
    status: str  # current | stale | not_collected | no_cache | archived | error
    live_files: int
    live_bytes: int
    collected_files: int
    collected_bytes: int
    at_risk: list[str]  # live source paths with no verified copy in data/foz/
    detail: str

    @property
    def safe_to_uninstall(self) -> bool:
        return self.status in SAFE_STATUSES


def _cache_key(source: str | Path) -> str:
    """Identity of a cache file that survives the drive being remounted.

    Manifests record absolute source paths, and those rot: the SataSSD library
    moved from /media/methos/SataSSD to /mnt/SataSSD, which would make every
    file on it look uncollected. Everything below `steamapps/` is stable --
    shadercache/<appid>/fozpipelinesv6/<...> is assigned by Steam, and a given
    appid lives in exactly one library."""
    parts = Path(source).parts
    if "steamapps" in parts:
        return "/".join(parts[parts.index("steamapps"):])
    return "/".join(parts[-3:])


def _collected_index(dest_dir: Path) -> dict[str, dict]:
    """Map cache key -> manifest entry, for entries whose destination file is
    still present at the recorded size. Entries whose copy was deleted are
    omitted, so a manifest left behind by a removed collection reads as
    "not collected" rather than as a false guarantee."""
    manifest_path = dest_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    index: dict[str, dict] = {}
    for entry in util.read_json(manifest_path).get("files", []):
        dest = dest_dir / entry["dest_name"]
        if dest.is_file() and dest.stat().st_size == entry["size"]:
            index[_cache_key(entry["source"])] = entry
    return index


def _is_saved(src: Path, entry: dict | None, deep: bool) -> bool:
    """True when `src` is already safely copied. Size-only by default because
    the shallow check runs over the whole 22.95 GB corpus; `deep` re-hashes the
    source, which costs a full read of every live cache."""
    if entry is None:
        return False
    if src.stat().st_size != entry["size"]:
        return False
    return not deep or provenance.sha256_file(src) == entry["sha256"]


def check_game(slug: str, dest_root: Path | None = None, deep: bool = False) -> CacheStatus:
    """Compare a game's live shadercache against what is collected in
    data/foz/<slug>/. Never raises -- a broken game config is a status, because
    the whole point is to survey every game in one pass."""
    try:
        game_cfg = config.load_game_config(slug)
    except config.ConfigError as exc:
        return CacheStatus(slug, False, "error", 0, 0, 0, 0, [], str(exc))

    if game_cfg.game.appid is None:
        return CacheStatus(slug, False, "error", 0, 0, 0, 0, [],
                           "no appid (not a Steam title)")

    installed = steam.find_app_library(game_cfg.game.appid) is not None
    sources = steam.shadercache_foz(game_cfg)
    live_bytes = sum(p.stat().st_size for p in sources)

    dest_dir = (dest_root or (config.load_tcc_config().paths.data_dir / "foz")) / slug
    index = _collected_index(dest_dir)
    at_risk = [str(p) for p in sources if not _is_saved(p, index.get(_cache_key(p)), deep)]

    if not sources and not index:
        status = "no_cache"
        detail = "never played, or Steam has no cache for it"
    elif not sources:
        status = "archived"
        detail = "no live cache; the collected copy is all that remains"
    elif not index:
        status = "not_collected"
        detail = f"{len(sources)} live file(s), nothing collected"
    elif at_risk:
        status = "stale"
        detail = f"{len(at_risk)} of {len(sources)} live file(s) not in the collection"
    else:
        status = "current"
        detail = f"all {len(sources)} live file(s) collected" + (" and hash-verified" if deep else "")

    return CacheStatus(
        slug=slug,
        installed=installed,
        status=status,
        live_files=len(sources),
        live_bytes=live_bytes,
        collected_files=len(index),
        collected_bytes=sum(e["size"] for e in index.values()),
        at_risk=at_risk,
        detail=detail,
    )


def check_all(slugs: list[str] | None = None, deep: bool = False) -> list[CacheStatus]:
    if slugs is None:
        slugs = sorted(p.stem for p in config.games_dir().glob("*.toml"))
    return [check_game(slug, deep=deep) for slug in slugs]

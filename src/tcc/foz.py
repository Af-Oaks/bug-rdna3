"""Fossilize (.foz) database operations: snapshot, delta, extract, replay, disasm.

Empirical notes (Phase 2, verified against build/install/bin on this machine
and a real vkd3d-proton database -- data/foz/remnant2/steamapp_pipeline_cache.foz,
12307 shader modules / 5035 graphics / 8088 compute / 0 raytracing pipelines):

- fossilize-list's positional <database path> accepts a .foz directly.
  Output is one hex hash per line (optionally followed by size info with
  --size); the hash is always the first whitespace-separated token.

- fossilize-prune's --skip-<type> flags reliably remove EXACTLY the
  requested hash for small counts (verified exact for 10/100/500/1000
  hashes), but silently retain MORE than expected once the skip-list grows
  into the thousands (e.g. skipping all-but-one of 5035 graphics hashes,
  13000+ total --skip-* args, still left 78 survivors instead of 1) --
  this looks like an argument-accumulation bug/limit in this vendored
  build, not documented behavior. Do NOT rely on "--skip the complement"
  to build a keep-only-N-hashes database at real-world scale.

- fossilize-prune's --filter-<type> flags reliably GUARANTEE the requested
  hash(es) end up in the output db (verified: 1-hash and 10-hash cases both
  retained 100% of the requested hashes), but also retain a small constant
  "bonus" set of unrelated pipelines as a side effect (~77-87 extra graphics
  pipelines, independent of which or how many hashes were requested --
  even a nonexistent hash produced ~77 survivors). This is some
  undocumented default/fallback behavior in this build. It is harmless for
  our purposes: stats/isa/disasm only need the requested hashes present and
  loadable, so a superset scene.foz is acceptable. We therefore use
  --filter-<type> per requested hash and then verify presence via
  fossilize-list (hard error if a requested hash is still missing).

- fossilize-disasm's positional argument DOES accept a full .foz directly,
  despite the --help usage synopsis literally saying "state.json" (that
  text is misleading for this build -- verified empirically: it replays the
  whole database, filtered by --filter-<type>, same flag names as prune but
  DIFFERENT semantics here: fossilize-disasm's --filter-<type> selects
  EXACTLY the one requested pipeline, no bonus companions observed).
  --output must be an existing directory; fossilize-disasm writes one file
  per shader stage inside it, named
  "<shader_module_hash>.<entry_point>.<pipeline_hash>.<stage_ext>".
  --target isa emits three concatenated sections per file: "Representation:
  NIR Shader(s)", "Representation: ACO IR", and "Representation: Assembly
  (Final Assembly)" -- the last is the real RDNA ISA (s_/v_ mnemonics +
  hex encoding) that Phase 4's isa.py will parse.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import config, toolchain, util
from .session import Session

TAGS = {"modules": 4, "graphics": 6, "compute": 7, "raytracing": 9}
_PIPELINE_TAGS = {"graphics": 6, "compute": 7, "raytracing": 9}
_FILTER_FLAGS = {"graphics": "--filter-graphics", "compute": "--filter-compute", "raytracing": "--filter-raytracing"}


class FozError(Exception):
    """Raised for fossilize tool failures or missing databases."""


def _tool(name: str):
    info = toolchain.resolve(name)
    if info.origin == "missing":
        raise FozError(f"{name} not found (see `tcc doctor`)")
    return info.path


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def snapshot(session: Session, game: str, label: str) -> list[Path]:
    """Copy every file matched by the game's foz cache_glob into
    <session>/foz/<label>/. Steam's fozpipelinesv6 shard files often lack a
    .foz extension (e.g. steamapprun_pipeline_cache.<N>), so we copy
    whatever the glob matches, whatever its name."""
    cfg = config.load_tcc_config()
    game_cfg = config.load_game_config(game)
    if game_cfg.game.appid is None or not game_cfg.foz.cache_glob:
        raise FozError(f"{game}: no Steam foz cache_glob configured for this game (native-cli/non-steam title?)")

    pattern = game_cfg.foz.cache_glob.format(appid=game_cfg.game.appid)
    matches = sorted(cfg.paths.steam_root.glob(pattern))
    if not matches:
        raise FozError(
            f"No files matched {cfg.paths.steam_root / pattern}; "
            "has the game been launched and played yet?"
        )

    dest_dir = util.ensure_dir(session.subdir("foz") / label)
    copied = []
    for src in matches:
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        session.record_artifact(dest, kind=f"foz_snapshot_{label}", producer="tcc foz snapshot", confidence="exact")
        copied.append(dest)
    return copied


def import_foz(session: Session, game: str, path: Path) -> Path:
    """Copy an existing .foz file into the session (kind 'foz_import').
    Fast path for validating the stats pipeline against a previously
    captured database without a fresh in-game snapshot."""
    src = Path(path)
    if not src.is_file():
        raise FozError(f"No such foz file: {src}")
    dest_dir = util.ensure_dir(session.subdir("foz"))
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    session.record_artifact(dest, kind="foz_import", producer=f"tcc foz import --game {game}", confidence="exact")
    return dest


# ---------------------------------------------------------------------------
# list_hashes / delta
# ---------------------------------------------------------------------------


def list_hashes(foz_path: Path, tag: int) -> set[str]:
    tool = _tool("fossilize-list")
    proc = subprocess.run(
        [str(tool), str(foz_path), "--tag", str(tag)], capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        raise FozError(f"fossilize-list failed on {foz_path} (tag {tag}): {proc.stderr[-2000:]}")
    return {line.split()[0] for line in proc.stdout.splitlines() if line.strip()}


def _union_hashes(files: Iterable[Path], tag: int) -> set[str]:
    result: set[str] = set()
    for f in files:
        result |= list_hashes(f, tag)
    return result


def delta(session: Session) -> dict[str, int]:
    """hashes(after) - hashes(before), per tag {4: modules, 6: graphics,
    7: compute, 9: raytracing}. Writes <session>/foz/delta.json (full hash
    lists per tag) and returns per-tag new-hash counts."""
    before_dir = session.subdir("foz") / "before"
    after_dir = session.subdir("foz") / "after"
    before_files = sorted(before_dir.glob("*")) if before_dir.is_dir() else []
    after_files = sorted(after_dir.glob("*")) if after_dir.is_dir() else []
    if not after_files:
        raise FozError(f"No 'after' snapshot in {after_dir}; run `tcc foz snapshot --label after` first.")

    new_hashes: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for name, tag in TAGS.items():
        before_set = _union_hashes(before_files, tag)
        after_set = _union_hashes(after_files, tag)
        new_hashes[name] = sorted(after_set - before_set)
        counts[name] = len(new_hashes[name])

    out_path = session.subdir("foz") / "delta.json"
    util.write_json(out_path, new_hashes)
    session.record_artifact(out_path, kind="foz_delta", producer="tcc foz delta", confidence="exact")
    return counts


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def classify_hashes(foz_path: Path, hashes: Iterable[str]) -> dict[str, list[str]]:
    """Bucket hashes by pipeline type (graphics/compute/raytracing) by
    checking tag membership in foz_path. Needed because fossilize-prune's
    --filter-<type> flags are type-specific."""
    wanted = set(hashes)
    buckets: dict[str, list[str]] = {name: [] for name in _PIPELINE_TAGS}
    for name, tag in _PIPELINE_TAGS.items():
        present = list_hashes(foz_path, tag)
        buckets[name] = sorted(wanted & present)
    return buckets


def _default_source_foz(session: Session) -> Path:
    after_dir = session.subdir("foz") / "after"
    after_files = sorted(after_dir.glob("*")) if after_dir.is_dir() else []
    if len(after_files) == 1:
        return after_files[0]
    if len(after_files) > 1:
        raise FozError(
            f"Multiple files in {after_dir}; pass source_foz explicitly "
            "(merge them with fossilize-merge-db first if they are shards)."
        )
    imported = sorted(session.subdir("foz").glob("*.foz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if imported:
        return imported[0]
    raise FozError(
        f"No foz database found for session {session.session_id}. "
        "Run `tcc foz snapshot --label after` or `tcc foz import` first, "
        "or pass source_foz explicitly."
    )


def extract(session: Session, hashes: list[str] | None = None, source_foz: Path | None = None) -> Path:
    """Build a scene-scoped <session>/foz/scene.foz via fossilize-prune.

    With hashes=None: a plain orphan-sweep prune (fossilize-prune's default
    behavior with no filter flags trims shader modules/layouts that are no
    longer referenced by any surviving pipeline; all pipelines survive).

    With hashes given: --filter-<type> per hash (see module docstring for
    why, not --skip-the-complement), then a hard presence check via
    fossilize-list -- silent data loss would be worse than a crash here.
    """
    source = Path(source_foz) if source_foz else _default_source_foz(session)
    out_path = session.subdir("foz") / "scene.foz"
    tool = _tool("fossilize-prune")

    argv = [str(tool), "--input-db", str(source), "--output-db", str(out_path)]
    if hashes:
        buckets = classify_hashes(source, hashes)
        classified = {h for group in buckets.values() for h in group}
        unclassified = set(hashes) - classified
        if unclassified:
            raise FozError(f"hashes not found in {source} as graphics/compute/raytracing: {sorted(unclassified)}")
        for name in _PIPELINE_TAGS:
            for h in buckets[name]:
                argv += [_FILTER_FLAGS[name], h]

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise FozError(f"fossilize-prune failed: {proc.stderr[-2000:]}")

    if hashes:
        present = set()
        for tag in _PIPELINE_TAGS.values():
            present |= list_hashes(out_path, tag)
        missing = set(hashes) - present
        if missing:
            raise FozError(f"fossilize-prune did not retain requested hashes: {sorted(missing)}")

    session.record_artifact(out_path, kind="scene_foz", producer="tcc foz extract", confidence="exact")
    return out_path


# ---------------------------------------------------------------------------
# replay_stats
# ---------------------------------------------------------------------------


@dataclass
class ReplayResult:
    csv_path: Path
    returncode: int
    num_rows: int
    failure_count: int
    stdout: str
    stderr: str


def replay_stats(
    foz_path: Path,
    out_path: Path,
    env: dict[str, str],
    threads: int = 4,
    timeout_s: int = 30,
) -> ReplayResult:
    """Run fossilize-replay --enable-pipeline-stats against foz_path.

    Despite the flag not naming an extension, the output is CSV (verified:
    header row starting "Database,Pipeline type,Pipeline hash,..."), one row
    per pipeline *stage* (vertex/fragment/compute/...). Individual pipeline
    failures (RT/vkd3d quirks) do not abort the run -- fossilize-replay
    skips and logs them internally; --timeout-seconds bounds each one.
    """
    import os

    tool = _tool("fossilize-replay")
    util.ensure_dir(out_path.parent)
    argv = [
        str(tool),
        "--enable-pipeline-stats", str(out_path),
        "--num-threads", str(threads),
        "--timeout-seconds", str(timeout_s),
        str(foz_path),
    ]
    run_env = dict(os.environ)
    run_env.update(env)
    # Generous outer bound: --timeout-seconds is *per pipeline*; this is a
    # safety net against the whole process wedging, not the normal path.
    outer_timeout = max(1800, timeout_s * 200)
    try:
        proc = subprocess.run(argv, env=run_env, capture_output=True, text=True, timeout=outer_timeout)
        returncode = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")

    failure_count = sum(
        1 for line in stderr.splitlines() if "fail" in line.lower() or "timeout" in line.lower()
    )
    num_rows = 0
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            num_rows = max(sum(1 for _ in fh) - 1, 0)  # minus header

    return ReplayResult(out_path, returncode, num_rows, failure_count, stdout, stderr)


# ---------------------------------------------------------------------------
# disasm
# ---------------------------------------------------------------------------


def disasm(
    foz_path: Path,
    pipeline_hash: str,
    pipeline_type: str,
    out_dir: Path,
    env: dict[str, str],
    target: str = "isa",
) -> list[Path]:
    """Disassemble one pipeline via fossilize-disasm. pipeline_type must be
    one of "graphics"/"compute"/"raytracing" (see classify_hashes()).
    Returns the output file(s) written (one per shader stage)."""
    import os

    if pipeline_type not in _FILTER_FLAGS:
        raise FozError(f"pipeline_type must be one of {sorted(_FILTER_FLAGS)}, got {pipeline_type!r}")

    tool = _tool("fossilize-disasm")
    util.ensure_dir(out_dir)
    argv = [
        str(tool),
        str(foz_path),
        "--target", target,
        _FILTER_FLAGS[pipeline_type], pipeline_hash,
        "--output", str(out_dir),
    ]
    run_env = dict(os.environ)
    run_env.update(env)
    proc = subprocess.run(argv, env=run_env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise FozError(f"fossilize-disasm failed for {pipeline_hash}: {proc.stderr[-2000:]}")

    return sorted(out_dir.glob(f"*.{pipeline_hash}.*"))

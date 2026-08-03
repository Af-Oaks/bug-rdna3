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

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core import config, provenance, toolchain, util
from core.errors import TccError
from core.session import Session

TAGS = {"modules": 4, "graphics": 6, "compute": 7, "raytracing": 9}
_PIPELINE_TAGS = {"graphics": 6, "compute": 7, "raytracing": 9}
_FILTER_FLAGS = {"graphics": "--filter-graphics", "compute": "--filter-compute", "raytracing": "--filter-raytracing"}


class FozError(TccError):
    """Raised for fossilize tool failures or missing databases."""


def _tool(name: str, session: Session | None = None):
    """Resolve a fossilize binary, recording WHICH one into the session.

    resolve() may pick build/install/bin (local), tools/ (vendored) or PATH
    (system) and those are different programs producing different output. A
    result that will not reproduce is usually explained by this line."""
    info = toolchain.resolve(name)
    if info.origin == "missing":
        raise FozError(f"{name} not found (see `tcc doctor`)")
    if session is not None:
        session.record_tool(name, str(info.path), info.origin)
    return info.path


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def snapshot(session: Session, game: str, label: str) -> list[Path]:
    """Copy every file matched by the game's foz cache_glob into
    <session>/foz/<label>/. The glob is resolved across ALL Steam library
    folders (games live on several drives here) via steam.shadercache_foz,
    which also handles both cache layouts: new steam_pipeline_cache.foz
    files and the legacy steamapprun_pipeline_cache.<hex>/ directory that
    nests the real .foz inside it."""
    from launcher import steam as steam_mod

    game_cfg = config.load_game_config(game)
    if game_cfg.game.appid is None or not game_cfg.foz.cache_glob:
        raise FozError(f"{game}: no Steam foz cache_glob configured for this game (native-cli/non-steam title?)")

    matches = steam_mod.shadercache_foz(game_cfg)
    if not matches:
        raise FozError(
            f"No files matched {game_cfg.foz.cache_glob!r} (appid "
            f"{game_cfg.game.appid}) in any Steam library; "
            "has the game been launched and played yet?"
        )

    from .collect import classify, flat_name

    dest_dir = util.ensure_dir(session.subdir("foz") / label)
    copied = []
    taken: set[str] = set()
    for src in matches:
        name = flat_name(src, taken)
        taken.add(name)
        dest = dest_dir / name
        # The invariant delta()'s run_created depends on: a run-recorded source
        # must still be identifiable as one after the copy. Losing it would not
        # raise anywhere -- run_created would just silently become 0, which
        # reads as "this run compiled nothing new" rather than as a bug.
        if classify(src) == "run_recorded" and "steamapprun" not in name:
            raise FozError(
                f"snapshot naming lost the run-recorded marker: {src} -> {name}. "
                "delta()'s run_created depends on 'steamapprun' surviving into the "
                "copied filename; fix collect.flat_name() before continuing."
            )
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


def snapshot_labels(session: Session) -> list[str]:
    """Phase labels captured in this session, oldest first."""
    foz_dir = session.subdir("foz")
    if not foz_dir.is_dir():
        return []
    return sorted(d.name for d in foz_dir.iterdir()
                  if d.is_dir() and any(d.iterdir()))


def delta(session: Session, before: str = "before", after: str = "after") -> dict[str, dict[str, int]]:
    """hashes(after) - hashes(before), per tag {4: modules, 6: graphics,
    7: compute, 9: raytracing}. Writes <session>/foz/delta.<before>_<after>.json
    and returns {"new": per-tag counts, "run_created": per-tag counts}.

    Labels are arbitrary, not just before/after, because pipeline creation is
    phased: three sequential runs of the same Metro EE benchmark created 63,699
    then 2,526 then 1,178 graphics pipelines. Almost everything is compiled at
    load, so snapshotting `menu` / `loaded` / `done` and diffing adjacent pairs
    separates "what loading compiled" from "what the scene compiled" -- which a
    single before/after pair cannot.

    "run_created" restricts the new hashes to steamapprun_* cache files --
    the ones Steam's Fossilize layer records during YOUR launches. This
    matters because Steam may download its community pre-built cache
    (steamapp_pipeline_cache.foz, no "run") DURING the session window
    (observed with Metro EE: 142MB pre-cache landed mid-run), and those
    pipelines were never created by the local machine. Thesis analysis of
    "what did this run create" must use run_created, not new."""
    before_dir = session.subdir("foz") / before
    after_dir = session.subdir("foz") / after
    before_files = sorted(p for p in before_dir.glob("*") if p.is_file()) if before_dir.is_dir() else []
    after_files = sorted(p for p in after_dir.glob("*") if p.is_file()) if after_dir.is_dir() else []
    if not after_files:
        known = snapshot_labels(session) or ["none"]
        raise FozError(
            f"No {after!r} snapshot in {after_dir}. Captured labels: {', '.join(known)}. "
            f"Run `tcc foz snapshot --label {after}` first."
        )

    # steamapprun_* is the run-recorded cache in both layouts. This works
    # ONLY because snapshot() prefixes the parent directory name whenever that
    # parent is not "fozpipelinesv6" (and the GRANDPARENT name on collision),
    # so the legacy layout's steamapprun_<hex>/ directory survives into the
    # copied filename. Change that naming and run_created silently becomes 0 --
    # which reads as a plausible result, not an error. Asserted below.
    run_files = [f for f in after_files if "steamapprun" in f.name]

    new_hashes: dict[str, list[str]] = {}
    run_created: dict[str, list[str]] = {}
    counts_new: dict[str, int] = {}
    counts_run: dict[str, int] = {}
    for name, tag in TAGS.items():
        before_set = _union_hashes(before_files, tag)
        after_set = _union_hashes(after_files, tag)
        new = after_set - before_set
        run_set = _union_hashes(run_files, tag) & new if run_files else set()
        new_hashes[name] = sorted(new)
        run_created[name] = sorted(run_set)
        counts_new[name] = len(new)
        counts_run[name] = len(run_set)

    name = "delta.json" if (before, after) == ("before", "after") else f"delta.{before}_{after}.json"
    out_path = session.subdir("foz") / name
    util.write_json(out_path, {"before": before, "after": after,
                               "new": new_hashes, "run_created": run_created})
    session.record_artifact(out_path, kind="foz_delta",
                            producer=f"tcc foz delta --before {before} --after {after}",
                            confidence="exact")
    return {"new": counts_new, "run_created": counts_run}


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


def resolve_foz(session: Session, explicit: Path | None = None, use_corpus: bool = True) -> Path:
    """THE rule for "which database does this command analyse".

    Precedence, in order, raising rather than guessing:

      1. an explicit path from the caller
      2. data/corpus/<game>/corpus.foz -- every collected .foz for this game,
         merged and deduplicated (see corpus.py). This is the default because
         analysing one arbitrarily-chosen file discards up to 52% of the data
         collected for a game.
      3. <session>/foz/scene.foz -- a deliberately scoped subset
      4. the single file in <session>/foz/after/
      5. the single *.foz imported into <session>/foz/

    Selection is never by mtime. The previous implementations picked "newest
    file" (stats.py) and "single file in after/" (foz.py) independently, so the
    same session could be analysed against different databases by two commands,
    and re-running months later could silently select different input.
    """
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise FozError(f"No such foz database: {path}")
        return path

    if use_corpus:
        from . import corpus as corpus_mod

        candidate = corpus_mod.corpus_foz(session.game)
        if candidate.is_file():
            return candidate

    scene = session.subdir("foz") / "scene.foz"
    if scene.is_file():
        return scene

    after_dir = session.subdir("foz") / "after"
    after_files = sorted(p for p in after_dir.glob("*") if p.is_file()) if after_dir.is_dir() else []
    if len(after_files) == 1:
        return after_files[0]
    if len(after_files) > 1:
        raise FozError(
            f"{len(after_files)} files in {after_dir} and no corpus for "
            f"{session.game!r}. Build one with `tcc corpus build --game "
            f"{session.game}`, or pass an explicit path."
        )

    imported = sorted(p for p in session.subdir("foz").glob("*.foz") if p.is_file())
    if len(imported) == 1:
        return imported[0]
    if len(imported) > 1:
        raise FozError(
            f"{len(imported)} databases in {session.subdir('foz')} and no corpus "
            f"for {session.game!r}; pass an explicit path or build a corpus."
        )

    raise FozError(
        f"No foz database for session {session.session_id}. Run "
        "`tcc foz snapshot --label after`, `tcc foz import`, or "
        f"`tcc corpus build --game {session.game}` first."
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
    # Scene extraction scopes DOWN from one captured database, so it must not
    # silently widen to the merged corpus: use_corpus=False.
    source = resolve_foz(session, explicit=source_foz, use_corpus=False)
    out_path = session.subdir("foz") / "scene.foz"
    tool = _tool("fossilize-prune", session)

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


def replay_stats(
    session: Session,
    step: str,
    foz_path: Path,
    out_path: Path,
    env: dict[str, str],
    threads: int = 4,
    timeout_s: int = 30,
) -> ReplayResult:
    """Run fossilize-replay --enable-pipeline-stats against foz_path.

    Goes through provenance.run_recorded, which tees stdout/stderr into
    <session>/logs/<step>.*.log AND records a step carrying the VK_/RADV_/
    MESA_ environment that was in effect. That environment snapshot is the
    only machine-checkable record of WHICH COMPILER produced these numbers --
    without it a stats table cannot be re-verified months later, and the ICD
    swap is provable only by watching strace by hand.

    Despite the flag not naming an extension, the output is CSV (verified:
    header row starting "Database,Pipeline type,Pipeline hash,..."), one row
    per pipeline *stage* (vertex/fragment/compute/...). Individual pipeline
    failures (RT/vkd3d quirks) do not abort the run -- fossilize-replay
    skips and logs them internally; --timeout-seconds bounds each one.
    """
    tool = _tool("fossilize-replay", session)
    util.ensure_dir(out_path.parent)
    argv = [
        str(tool),
        "--enable-pipeline-stats", str(out_path),
        "--num-threads", str(threads),
        "--timeout-seconds", str(timeout_s),
        str(foz_path),
    ]
    # --timeout-seconds is *per pipeline*; this outer bound is a safety net
    # against the whole process wedging, not the normal path.
    proc = provenance.run_recorded(
        session, step, argv, env=env, timeout=max(1800, timeout_s * 200)
    )

    stderr_log = session.subdir("logs") / f"{step.replace('/', '_').replace(' ', '_')}.stderr.log"
    failure_count = 0
    if stderr_log.is_file():
        failure_count = sum(
            1 for line in stderr_log.read_text(encoding="utf-8", errors="replace").splitlines()
            if "fail" in line.lower() or "timeout" in line.lower()
        )

    num_rows = 0
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            num_rows = max(sum(1 for _ in fh) - 1, 0)  # minus header

    return ReplayResult(out_path, proc.returncode, num_rows, failure_count)


# ---------------------------------------------------------------------------
# disasm
# ---------------------------------------------------------------------------


def disasm(
    session: Session,
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

    if pipeline_type not in _FILTER_FLAGS:
        raise FozError(f"pipeline_type must be one of {sorted(_FILTER_FLAGS)}, got {pipeline_type!r}")

    tool = _tool("fossilize-disasm", session)
    util.ensure_dir(out_dir)
    argv = [
        str(tool),
        str(foz_path),
        "--target", target,
        _FILTER_FLAGS[pipeline_type], pipeline_hash,
        "--output", str(out_dir),
    ]
    proc = provenance.run_recorded(
        session, f"disasm_{pipeline_hash[:12]}", argv, env=env, timeout=120
    )
    if proc.returncode != 0:
        raise FozError(
            f"fossilize-disasm failed for {pipeline_hash} (returncode "
            f"{proc.returncode}); see logs/disasm_{pipeline_hash[:12]}.stderr.log"
        )

    return sorted(out_dir.glob(f"*.{pipeline_hash}.*"))

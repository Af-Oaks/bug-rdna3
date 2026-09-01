"""Merge every .foz collected for a game into one database, keeping provenance.

Why this exists
---------------
Analysis used to run against a single arbitrarily-chosen .foz -- `scene.foz`, or
whichever file happened to be newest. Everything else collected for that game was
ignored. Measured 2026-08-03, that discards 52% of re6, 50% of remnant2 and 42%
of helldivers2 by size.

Fossilize databases are content-addressed, so merging N files yields the UNION of
their hashes, never the concatenation -- there is no double-counting risk.
Verified against real data:

    remnant2       5,035 + 5,038  ->  5,038 graphics   (one file was a subset)
    mechabellum    best 25,797    -> 27,382 graphics   (+6.1%)
    cyberpunk2077  best 19,316    -> 23,365 graphics   (+21.0%)

The catch, and the reason this module is more than a shell script
-----------------------------------------------------------------
Merging destroys the distinction the evidence chain rests on: `run_recorded`
(steamapprun_* -- pipelines THIS machine compiled) versus `steam_precache`
(possibly downloaded from Steam's community cache). After the merge there is no
file boundary left to tell them apart.

So the hash -> provenance index is built BEFORE merging and persisted beside the
corpus. `analysis.stats` joins it back on, which means you get the coverage of
every file AND keep the ability to say "this pipeline was compiled here".

Cost
----
The merged corpus roughly duplicates the archive on disk (~20 GB for all 18
games), so building is per-game and explicit, never automatic. `data/foz/` is the
verified archive and is never mutated: the largest source is COPIED to become the
merge base, because fossilize-merge-db appends into its first argument and
starting from the largest file minimises I/O.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core import config, provenance, util

from . import collect
from .foz import TAGS, FozError, list_hashes, _tool

#: Tags whose hashes are worth indexing by provenance. Modules (4) are shared
#: between pipelines and carry no run/precache meaning of their own.
_INDEXED_TAGS = {name: tag for name, tag in TAGS.items() if name != "modules"}


class CorpusError(FozError):
    """Corpus build/lookup failures."""


@dataclass
class CorpusResult:
    slug: str
    foz_path: Path
    index_path: Path
    source_count: int
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    best_single: dict[str, int] = field(default_factory=dict)

    def gain(self, tag_name: str = "graphics") -> tuple[int, int]:
        """(merged total, best single file) for one tag -- the coverage the
        merge bought over what the old single-file selection would have used."""
        return self.counts.get(tag_name, {}).get("total", 0), self.best_single.get(tag_name, 0)


def corpus_dir(slug: str, root: Path | None = None) -> Path:
    base = root or (config.load_tcc_config().paths.data_dir / "corpus")
    return base / slug


def corpus_foz(slug: str, root: Path | None = None) -> Path:
    return corpus_dir(slug, root) / "corpus.foz"


def corpus_index(slug: str, root: Path | None = None) -> Path:
    return corpus_dir(slug, root) / "corpus.json"


def _source_files(slug: str, foz_root: Path | None = None) -> list[Path]:
    src_dir = (foz_root or (config.load_tcc_config().paths.data_dir / "foz")) / slug
    if not src_dir.is_dir():
        raise CorpusError(f"{slug}: nothing collected at {src_dir}; run `tcc collect --game {slug}`")
    return sorted(p for p in src_dir.glob("*.foz") if p.is_file())


def build_index(sources: list[Path]) -> dict:
    """Hash -> provenance, computed BEFORE the merge while file boundaries exist.

    Only the run_recorded set is stored explicitly; steam_precache is derivable
    as (total - run_recorded), which keeps metro-ee's 102k graphics hashes to
    roughly 1.7 MB instead of several times that."""
    per_tag_all: dict[str, set[str]] = {name: set() for name in _INDEXED_TAGS}
    per_tag_run: dict[str, set[str]] = {name: set() for name in _INDEXED_TAGS}

    for src in sources:
        kind = collect.classify(src)
        for name, tag in _INDEXED_TAGS.items():
            hashes = list_hashes(src, tag)
            per_tag_all[name] |= hashes
            if kind == "run_recorded":
                per_tag_run[name] |= hashes

    counts = {
        name: {
            "total": len(per_tag_all[name]),
            "run_recorded": len(per_tag_run[name]),
            "steam_precache": len(per_tag_all[name] - per_tag_run[name]),
        }
        for name in _INDEXED_TAGS
    }
    return {
        "counts": counts,
        "run_recorded": {name: sorted(per_tag_run[name]) for name in _INDEXED_TAGS},
    }


def _best_single(sources: list[Path], tag_name: str = "graphics") -> tuple[int, Path | None]:
    """Largest per-file hash count for one tag -- the baseline the merge beats."""
    tag = _INDEXED_TAGS[tag_name]
    best, winner = 0, None
    for src in sources:
        n = len(list_hashes(src, tag))
        if n > best:
            best, winner = n, src
    return best, winner


def build(slug: str, root: Path | None = None, foz_root: Path | None = None,
          force: bool = False) -> CorpusResult:
    """Merge every collected .foz for `slug` into data/corpus/<slug>/corpus.foz
    and write the provenance index beside it."""
    sources = _source_files(slug, foz_root)
    if not sources:
        raise CorpusError(f"{slug}: no .foz files collected yet")

    out_foz = corpus_foz(slug, root)
    out_index = corpus_index(slug, root)
    if out_foz.exists() and not force:
        raise CorpusError(f"{slug}: {out_foz} already exists; pass force=True to rebuild")

    index = build_index(sources)
    best, _ = _best_single(sources)

    util.ensure_dir(out_foz.parent)
    # Append into the LARGEST source so the merge copies as little as possible.
    ordered = sorted(sources, key=lambda p: p.stat().st_size, reverse=True)
    base, rest = ordered[0], ordered[1:]
    tmp = out_foz.with_suffix(".foz.building")
    if tmp.exists():
        tmp.unlink()
    shutil.copy2(base, tmp)

    if rest:
        argv = [str(_tool("fossilize-merge-db")), str(tmp), *(str(p) for p in rest)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=7200)
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise CorpusError(f"{slug}: fossilize-merge-db failed: {proc.stderr[-2000:]}")

    tmp.replace(out_foz)

    payload = {
        "slug": slug,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "corpus_foz": str(out_foz),
        "sha256": provenance.sha256_file(out_foz),
        "size_bytes": out_foz.stat().st_size,
        "sources": [
            {
                "name": p.name,
                "kind": collect.classify(p),
                "size": p.stat().st_size,
            }
            for p in ordered
        ],
        "best_single_graphics": best,
        **index,
    }
    util.write_json(out_index, payload)

    return CorpusResult(
        slug=slug,
        foz_path=out_foz,
        index_path=out_index,
        source_count=len(sources),
        counts=index["counts"],
        best_single={"graphics": best},
    )


def load_index(slug: str, root: Path | None = None) -> dict | None:
    path = corpus_index(slug, root)
    return util.read_json(path) if path.is_file() else None


def provenance_lookup(slug: str, root: Path | None = None) -> dict[str, str]:
    """Flat hash -> "run_recorded" map for joining onto a stats table. Hashes
    absent from the map are steam_precache: the index stores only the
    run-recorded set, because that is the one that carries evidential weight."""
    index = load_index(slug, root)
    if not index:
        return {}
    lookup: dict[str, str] = {}
    for hashes in index.get("run_recorded", {}).values():
        for h in hashes:
            lookup[h] = "run_recorded"
    return lookup


def list_built(root: Path | None = None) -> list[dict]:
    base = root or (config.load_tcc_config().paths.data_dir / "corpus")
    if not base.is_dir():
        return []
    out = []
    for index_path in sorted(base.glob("*/corpus.json")):
        payload = util.read_json(index_path)
        out.append({
            "slug": payload["slug"],
            "built_at": payload["built_at"],
            "size_bytes": payload["size_bytes"],
            "sources": len(payload.get("sources", [])),
            "counts": payload.get("counts", {}),
            "best_single_graphics": payload.get("best_single_graphics", 0),
        })
    return out

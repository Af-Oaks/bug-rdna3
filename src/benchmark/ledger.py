"""One row per (workload, compiler revision) — where the three metrics meet.

Metric 1 says what the compiler emitted. Metric 3 says what that code cost the
GPU. Metric 2 says whether the player noticed. Each alone is a partial answer;
the ledger is what lets you read across them:

    static win + GPU win + frame win   a real improvement, fully traced
    static win + no GPU win            the metric you optimised was not the cost
    static + GPU win + no frame win    the shader is not hot enough to matter

All three are publishable. The third is the one a single metric would have
reported as a success.

The matrix is sparse on purpose. A shader added from a new game has no history
before its first run, and that is fine — every comparison is a per-shader,
within-run pair, never an average across time. Averaging the corpus would let a
shrinking corpus masquerade as an improvement, which is why `n_pipelines` and
`n_failed` are on every row.
"""

from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core import config, paths
from core.errors import TccError

FIELDS = [
    "run_id", "date", "game", "session_id", "cohort", "api",
    "compiler_rev", "driver_label",
    "n_pipelines", "n_ok", "n_failed", "n_unstable",
    # Metric 1 (compare.py)
    "m1_rows", "m1_verdict", "d_vgprs_mean", "d_max_waves_mean", "d_spilled_sum",
    # Metric 3 (shaderbench)
    "m3_shaders", "m3_mean_delta_pct", "m3_median_delta_pct", "m3_batches_faulted",
    # Metric 2 (game_bench)
    "fps_avg", "fps_1pct_low", "frametime_p99",
    "notes",
]


class LedgerError(TccError):
    pass


def ledger_path() -> Path:
    return config.load_tcc_config().paths.data_dir / "ledger" / "ledger.csv"


def compiler_rev() -> str:
    """Identify the compiler under test by the overlay's content, not by a
    version string. `custom_mesa_layer/` is what actually differs from stock, so
    hashing its tracked contents gives a revision that changes exactly when the
    compiler does."""
    root = paths.repo_root()
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h", "--", "custom_mesa_layer"],
            capture_output=True, text=True, timeout=15)
        rev = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    return rev or "unknown"


@dataclass
class Row:
    run_id: str
    date: str
    game: str = ""
    session_id: str = ""
    cohort: str = ""
    api: str = ""
    compiler_rev: str = ""
    driver_label: str = ""
    n_pipelines: int = 0
    n_ok: int = 0
    n_failed: int = 0
    n_unstable: int = 0
    m1_rows: int = 0
    m1_verdict: str = ""
    d_vgprs_mean: float = 0.0
    d_max_waves_mean: float = 0.0
    d_spilled_sum: float = 0.0
    m3_shaders: int = 0
    m3_mean_delta_pct: float = 0.0
    m3_median_delta_pct: float = 0.0
    m3_batches_faulted: int = 0
    fps_avg: float = 0.0
    fps_1pct_low: float = 0.0
    frametime_p99: float = 0.0
    notes: str = ""


def _metric(payload: dict, name: str, key: str) -> float:
    for m in payload.get("metrics", []):
        if m.get("metric") == name:
            return float(m.get(key, 0.0))
    return 0.0


def build_row(session, game: str, compare_json: Path | None = None,
              shaderbench_json: Path | None = None, bench_summary: Path | None = None,
              notes: str = "") -> Row:
    """Assemble one row from whichever metrics were actually run. Missing
    metrics stay zero rather than blocking the row: a run that only produced
    Metric 1 is still a valid, comparable observation."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    row = Row(run_id=f"{now.strftime('%Y%m%d-%H%M%S')}_{game}",
              date=now.isoformat(), game=game,
              session_id=getattr(session, "session_id", ""),
              compiler_rev=compiler_rev(), notes=notes)

    try:
        gc = config.load_game_config(game)
        row.cohort, row.api = gc.game.cohort, gc.game.api
    except config.ConfigError:
        pass

    if compare_json and Path(compare_json).is_file():
        p = json.loads(Path(compare_json).read_text(encoding="utf-8"))
        row.m1_rows = int(p.get("rows_joined", 0))
        row.m1_verdict = str(p.get("verdict", ""))
        row.d_vgprs_mean = _metric(p, "vgprs", "mean_delta")
        row.d_max_waves_mean = _metric(p, "max_waves", "mean_delta")
        row.d_spilled_sum = _metric(p, "spilled_vgprs", "total_delta")
        row.driver_label = "→".join(str(p.get("source", {}).get(k, "")) for k in ("label_a", "label_b"))

    if shaderbench_json and Path(shaderbench_json).is_file():
        p = json.loads(Path(shaderbench_json).read_text(encoding="utf-8"))
        deltas = p.get("deltas", [])
        row.m3_shaders = len(deltas)
        if deltas:
            pcts = sorted(d["delta_pct"] for d in deltas)
            row.m3_mean_delta_pct = round(sum(pcts) / len(pcts), 4)
            row.m3_median_delta_pct = round(pcts[len(pcts) // 2], 4)
        for d in p.get("drivers", {}).values():
            cov = d.get("coverage", {})
            row.n_pipelines += sum(cov.values())
            row.n_ok += cov.get("ok", 0)
            row.n_unstable += cov.get("unstable", 0)
            row.n_failed += cov.get("create_failed", 0) + cov.get("no_dispatch", 0) \
                + cov.get("faulted", 0) + cov.get("batch_faulted", 0)
            row.m3_batches_faulted += int(d.get("batches_faulted", 0))

    if bench_summary and Path(bench_summary).is_file():
        p = json.loads(Path(bench_summary).read_text(encoding="utf-8"))
        runs = p.get("runs", [])
        if runs:
            r0 = runs[0]
            row.fps_avg = float(r0.get("fps_avg") or 0.0)
            row.fps_1pct_low = float(r0.get("fps_1pct_low") or 0.0)
            row.frametime_p99 = float((r0.get("frametime_ms") or {}).get("p99") or 0.0)
    return row


def append(row: Row) -> Path:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: v for k, v in asdict(row).items() if k in FIELDS})
    return path


def load() -> list[dict]:
    path = ledger_path()
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def render(rows: list[dict]) -> str:
    if not rows:
        return "ledger is empty; run `tcc ledger add --session <id> --game <slug>`"
    cols = ["date", "game", "compiler_rev", "m1_verdict", "m1_rows",
            "m3_shaders", "m3_mean_delta_pct", "n_ok", "n_failed", "fps_avg"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    out = ["  ".join(c.ljust(widths[c]) for c in cols),
           "  ".join("-" * widths[c] for c in cols)]
    for r in rows:
        out.append("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
    return "\n".join(out)

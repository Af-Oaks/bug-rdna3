"""Metric 1 -- diff two stats tables produced by the same foz under two compilers.

Both sides replay byte-identical input, so every difference is attributable to
the compiler. See docs/METRICS_PLAN.md §2.3.

The first result that matters is the NULL verdict: stock vs custom, where the
custom ACO overlay is still unmodified, must come out `identical`. That zero is
what proves capture -> replay -> parse -> join -> aggregate is sound before the
compiler ever diverges. A non-zero here is either a real divergence or a harness
bug, and either way it gets explained before any later number is trusted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core import util
from core.errors import TccError
from core.session import Session

# Direction convention. Lower is better for cost metrics; higher is better for
# occupancy (max_waves is waves-per-SIMD -- more resident waves hide latency).
LOWER_IS_BETTER = [
    "vgprs", "sgprs", "spilled_vgprs", "spilled_sgprs", "code_size", "lds",
    "scratch", "instructions", "latency", "inverse_throughput", "valu", "salu",
    "vmem", "smem", "copies", "branches",
]
# `vopd_ratio`, not `vopd`. A raw VOPD count rises when a shader simply gets
# bigger, which would score as "improved" while nothing improved. The ratio
# (dual-issue instructions per VALU instruction) is what actually says whether
# the compiler paired more work.
HIGHER_IS_BETTER = ["max_waves", "vopd_ratio"]
# Direction-neutral: a CHANGE is the signal, neither sign is "better". Wave size
# is here because it is a compiler decision, not a cost -- and because VOPD is
# only emitted for wave32, so a wave-size shift explains VOPD shifts downstream.
NEUTRAL = ["subgroup_size"]
JOIN_KEY = ["pipeline_hash", "stage"]


class CompareError(TccError):
    pass


@dataclass
class MetricDelta:
    metric: str
    improved: int
    regressed: int
    unchanged: int
    total_delta: float
    mean_delta: float
    p50: float
    p95: float
    max_abs: float
    higher_is_better: bool
    neutral: bool = False


def _numeric_columns(a: pd.DataFrame, b: pd.DataFrame) -> list[str]:
    cols = []
    for c in LOWER_IS_BETTER + HIGHER_IS_BETTER + NEUTRAL:
        if c in a.columns and c in b.columns:
            if pd.api.types.is_numeric_dtype(a[c]) and pd.api.types.is_numeric_dtype(b[c]):
                cols.append(c)
    return cols


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """vopd_ratio = VOPD instructions per VALU instruction. Guarded against
    valu == 0 (shaders with no vector ALU work emit no dual-issue pairs, and
    0/0 is not an improvement)."""
    if "vopd" in df.columns and "valu" in df.columns:
        df = df.copy()
        df["vopd_ratio"] = (df["vopd"] / df["valu"].where(df["valu"] > 0)).fillna(0.0)
    return df


def compare_frames(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    """Join on (pipeline_hash, stage) and diff every shared numeric column."""
    for df, side in ((a, "a"), (b, "b")):
        missing = [k for k in JOIN_KEY if k not in df.columns]
        if missing:
            raise CompareError(f"side {side}: stats table is missing {missing}")

    a, b = _add_derived(a), _add_derived(b)

    # Duplicate (hash, stage) rows exist when one pipeline reports several
    # executables for a stage; collapse deterministically so the join is 1:1.
    # The count is REPORTED, not swallowed -- if the two sides collapse
    # different numbers of rows, the comparison is not like-for-like and you
    # need to know that before reading any delta below.
    a1 = a.groupby(JOIN_KEY, as_index=False).first()
    b1 = b.groupby(JOIN_KEY, as_index=False).first()
    collapsed_a = len(a) - len(a1)
    collapsed_b = len(b) - len(b1)

    merged = a1.merge(b1, on=JOIN_KEY, how="inner", suffixes=("_a", "_b"))
    only_a = len(a1) - len(merged)
    only_b = len(b1) - len(merged)

    metrics: list[MetricDelta] = []
    for col in _numeric_columns(a, b):
        d = (merged[f"{col}_b"] - merged[f"{col}_a"]).dropna()
        if d.empty:
            continue
        neutral = col in NEUTRAL
        higher = col in HIGHER_IS_BETTER
        # A neutral column has no better/worse: count movement in each
        # direction so a wave64 -> wave32 shift is visible without being
        # scored as an improvement it has not been shown to be.
        gain = d > 0 if (higher or neutral) else d < 0
        loss = d < 0 if (higher or neutral) else d > 0
        metrics.append(MetricDelta(
            metric=col,
            improved=int(gain.sum()),
            regressed=int(loss.sum()),
            unchanged=int((d == 0).sum()),
            total_delta=float(d.sum()),
            mean_delta=float(d.mean()),
            p50=float(d.quantile(0.50)),
            p95=float(d.quantile(0.95)),
            max_abs=float(d.abs().max()),
            higher_is_better=higher,
            neutral=neutral,
        ))

    # Neutral columns never contribute to a verdict -- they describe what the
    # compiler chose, not whether it did better.
    scored = [m for m in metrics if not m.neutral]
    any_change = any(m.improved or m.regressed for m in scored)
    if not any_change and only_a == 0 and only_b == 0:
        verdict = "identical"
    elif not any_change:
        verdict = "identical-stats-but-pipeline-set-differs"
    else:
        improved = sum(m.improved for m in scored)
        regressed = sum(m.regressed for m in scored)
        verdict = ("net-improvement" if improved > regressed * 1.05 else
                   "net-regression" if regressed > improved * 1.05 else "mixed")

    return {
        "verdict": verdict,
        "rows_a": int(len(a1)),
        "rows_b": int(len(b1)),
        "rows_joined": int(len(merged)),
        "collapsed": {"a": int(collapsed_a), "b": int(collapsed_b)},
        "compile_divergence": {"only_in_a": int(only_a), "only_in_b": int(only_b)},
        "metrics": [m.__dict__ for m in metrics],
    }


def render_markdown(result: dict, label_a: str, label_b: str) -> str:
    v = result["verdict"]
    banner = {
        "identical": "✅ IDENTICAL — zero deltas. The Metric-1 chain is sound.",
        "identical-stats-but-pipeline-set-differs": "⚠️ Stats identical, but the two sides compiled different pipeline sets.",
        "net-improvement": "📈 NET IMPROVEMENT",
        "net-regression": "📉 NET REGRESSION",
        "mixed": "🔀 MIXED",
    }.get(v, v)

    out = [f"# Compare: {label_a} vs {label_b}", "", f"**{banner}**", "",
           f"- rows {label_a}: {result['rows_a']:,} · rows {label_b}: {result['rows_b']:,} "
           f"· joined: {result['rows_joined']:,}",
           f"- compile divergence: only in {label_a}: "
           f"{result['compile_divergence']['only_in_a']:,} · only in {label_b}: "
           f"{result['compile_divergence']['only_in_b']:,}"]

    collapsed = result.get("collapsed", {})
    if collapsed.get("a") or collapsed.get("b"):
        warn = " ⚠️ **sides collapsed different amounts — not like-for-like**" \
            if collapsed.get("a") != collapsed.get("b") else ""
        out.append(f"- duplicate (hash, stage) rows collapsed: {label_a}: "
                   f"{collapsed['a']:,} · {label_b}: {collapsed['b']:,}{warn}")
    out.append("")

    if not result["metrics"]:
        out.append("_No shared numeric columns to compare._")
        return "\n".join(out)

    out += ["| metric | better | improved | regressed | unchanged | Σ delta | mean | p95 | max abs |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for m in result["metrics"]:
        better = ("neutral" if m.get("neutral") else
                  "higher" if m["higher_is_better"] else "lower")
        out.append(
            f"| `{m['metric']}` | {better} "
            f"| {m['improved']:,} | {m['regressed']:,} | {m['unchanged']:,} "
            f"| {m['total_delta']:,.4g} | {m['mean_delta']:.4f} | {m['p95']:.2f} | {m['max_abs']:.4g} |")

    wave = next((m for m in result["metrics"] if m["metric"] == "subgroup_size"), None)
    if wave and (wave["improved"] or wave["regressed"]):
        out += ["", "## ⚠️ Wave size changed", "",
                f"- shifted toward wave64 (Δ>0): **{wave['improved']:,}**",
                f"- shifted toward wave32 (Δ<0): **{wave['regressed']:,}**", "",
                "VOPD is only emitted for wave32, so any `vopd_ratio` movement above "
                "must be read against this row before it is attributed to better "
                "dual-issue pairing."]

    occ = next((m for m in result["metrics"] if m["metric"] == "max_waves"), None)
    if occ:
        out += ["", "## Occupancy (the most runtime-predictive column)", "",
                f"- waves regressions (Δ<0): **{occ['regressed']:,}**",
                f"- waves improvements (Δ>0): **{occ['improved']:,}**"]
    return "\n".join(out)


def run(session: Session | None, path_a: Path, path_b: Path,
        label_a: str, label_b: str, out_dir: Path) -> dict:
    if not path_a.is_file():
        raise CompareError(f"missing stats table: {path_a}")
    if not path_b.is_file():
        raise CompareError(f"missing stats table: {path_b}")

    a = pd.read_csv(path_a)
    b = pd.read_csv(path_b)
    result = compare_frames(a, b)
    result["source"] = {"a": str(path_a), "b": str(path_b), "label_a": label_a, "label_b": label_b}

    util.ensure_dir(out_dir)
    json_path = out_dir / f"compare.{label_a}_vs_{label_b}.json"
    md_path = out_dir / f"compare.{label_a}_vs_{label_b}.md"
    util.write_json(json_path, result)
    md_path.write_text(render_markdown(result, label_a, label_b), encoding="utf-8")

    if session is not None:
        for p in (json_path, md_path):
            session.record_artifact(p, kind="compare", producer="tcc compare", confidence="exact")
    return result

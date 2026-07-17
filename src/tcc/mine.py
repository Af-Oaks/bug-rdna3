"""Offender ranking over a session's stats table.

score = z(vgprs) + z(-max_waves) + z(code_size) + 3*z(spilled_vgprs)

Computed per-stage (vertex/fragment/compute/...) so pipelines aren't
z-scored against an unrelated population -- a compute shader's code_size
distribution has nothing to do with a fragment shader's.
"""

from __future__ import annotations

import pandas as pd

from . import stats as stats_mod
from .session import Session

_RANK_COLUMNS = {
    "score": ("score", False),
    "vgprs": ("vgprs", False),
    "spill": ("spilled_vgprs", False),
    "code_size": ("code_size", False),
    "waves": ("max_waves", True),  # ascending: fewest waves (worst occupancy) first
}


def _zscore(series: pd.Series) -> pd.Series:
    values = series.fillna(0)
    std = values.std(ddof=0)
    if not std or pd.isna(std):
        return pd.Series(0.0, index=series.index)  # zero-variance guard
    return (values - values.mean()) / std


def score(df: pd.DataFrame) -> pd.Series:
    result = pd.Series(0.0, index=df.index)
    for _, group in df.groupby("stage"):
        vgprs = _zscore(group["vgprs"]) if "vgprs" in group else 0.0
        neg_waves = _zscore(-group["max_waves"]) if "max_waves" in group else 0.0
        code_size = _zscore(group["code_size"]) if "code_size" in group else 0.0
        spilled = _zscore(group["spilled_vgprs"]) if "spilled_vgprs" in group else 0.0
        result.loc[group.index] = vgprs + neg_waves + code_size + 3 * spilled
    return result


def rank(
    session: Session,
    driver: str | None = None,
    top: int = 25,
    rank_by: str = "score",
) -> pd.DataFrame:
    """Rank pipelines by offender score, write <session>/stats/offenders.csv,
    and return the top-N rows."""
    df = stats_mod.load_session_stats(session, driver=driver)
    if df.empty:
        return df

    df = df.copy()
    df["score"] = score(df)
    col, ascending = _RANK_COLUMNS.get(rank_by, ("score", False))
    ranked = df.sort_values(col, ascending=ascending, kind="stable")

    out_path = session.subdir("stats") / "offenders.csv"
    ranked.to_csv(out_path, index=False)
    session.record_artifact(out_path, kind="offenders_table", producer="tcc mine", confidence="exact")
    return ranked.head(top)

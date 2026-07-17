"""Run fossilize-replay --enable-pipeline-stats and parse it into a tidy table.

Real header observed (Phase 2, RX 7800 XT / RADV stock, vkd3d-proton
Remnant II sample database, 13180 pipelines, 17730 stat rows, 64.5s wall,
zero replay failures):

    Database,Pipeline type,Pipeline hash,PSO wall duration (ns),
    PSO duration (ns),Stage duration (ns),Executable name,Subgroup size,
    Driver pipeline hash,SGPRs,VGPRs,Spilled SGPRs,Spilled VGPRs,Code size,
    LDS size,Scratch size,Subgroups per SIMD,Combined inputs,
    Combined outputs,Hash,Instructions,Copies,Branches,Latency,
    Inverse Throughput,VMEM Clause,SMEM Clause,Pre-Sched SGPRs,
    Pre-Sched VGPRs,VALU,SALU,VMEM,SMEM,VOPD

One row per pipeline *stage* (Executable name: vertex/fragment/compute/
mesh/"vertex + geometry"...), not per pipeline. `_classify_column` below is
substring-tolerant so minor header wording drift across Fossilize versions
degrades gracefully into `extra` instead of breaking the parse. Column
order matters for the "pre-sched" exclusion check, not for classification.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from . import config, foz as foz_mod
from .session import Session

_DRIVER_PROFILE = {"system": "baseline", "stock": "stock", "custom": "custom"}


class StatsError(Exception):
    pass


# ---------------------------------------------------------------------------
# CSV -> tidy rows
# ---------------------------------------------------------------------------


def _classify_column(header: str) -> str | None:
    h = header.strip().lower()
    # "Driver pipeline hash" also contains the substring "pipeline hash" --
    # it's a distinct internal driver hash (0x-prefixed), NOT the Fossilize
    # database key. Must be checked first or it silently clobbers
    # pipeline_hash with the wrong value (caught during Phase 2 real-run
    # verification: every row's pipeline_hash came out 0x-prefixed instead
    # of matching `fossilize-list` hashes).
    if "driver pipeline hash" in h:
        return "driver_pipeline_hash"
    if "pipeline hash" in h:
        return "pipeline_hash"
    if "pipeline type" in h:
        return "pipeline_type"
    if "executable name" in h:
        return "stage"
    if "pre-sched" in h or "pre sched" in h:
        return None  # explicitly NOT vgprs/sgprs even though it contains those substrings
    if "spilled" in h and "vgpr" in h:
        return "spilled_vgprs"
    if "spilled" in h and "sgpr" in h:
        return "spilled_sgprs"
    if "vgpr" in h:
        return "vgprs"
    if "sgpr" in h:
        return "sgprs"
    if "code size" in h:
        return "code_size"
    if "lds" in h:
        return "lds"
    if "scratch" in h:
        return "scratch"
    if "subgroups per simd" in h:
        return "max_waves"
    return None


def _coerce(value: str):
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def load_stats_csv(csv_path: Path, driver: str) -> pd.DataFrame:
    """Parse a raw fossilize-replay --enable-pipeline-stats CSV into the
    tidy row schema (see src/tcc/schemas/stats_table.schema.json)."""
    rows: list[dict] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        fields = [_classify_column(h) for h in header]
        for raw_row in reader:
            row: dict = {"driver": driver}
            extra: dict = {}
            for col_name, field, raw_value in zip(header, fields, raw_row):
                value = _coerce(raw_value)
                if field:
                    row[field] = value
                else:
                    extra[col_name] = value
            row["extra"] = json.dumps(extra)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# run: profile resolution + fossilize-replay + parse + save
# ---------------------------------------------------------------------------


def _default_foz_path(session: Session) -> Path:
    scene = session.subdir("foz") / "scene.foz"
    if scene.is_file():
        return scene
    candidates = sorted(session.subdir("foz").glob("*.foz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    raise StatsError(
        f"No foz database in {session.subdir('foz')}. Run `tcc foz import` or "
        "`tcc foz extract` first, or pass --foz explicitly."
    )


def run(
    session: Session,
    driver: str,
    foz_path: Path | None = None,
    threads: int | None = None,
    timeout_s: int | None = None,
    cfg: config.TccConfig | None = None,
) -> Path:
    """Run fossilize-replay --enable-pipeline-stats for `driver`
    (system|stock|custom -> baseline|stock|custom profile), parse the
    result, and save the tidy table to <session>/stats/stats.<driver>.csv."""
    if driver not in _DRIVER_PROFILE:
        raise StatsError(f"driver must be one of {sorted(_DRIVER_PROFILE)}, got {driver!r}")

    cfg = cfg or config.load_tcc_config()
    threads = threads or cfg.defaults.replay_threads
    timeout_s = timeout_s or cfg.defaults.replay_timeout_s
    foz_path = Path(foz_path) if foz_path else _default_foz_path(session)
    if not foz_path.is_file():
        raise StatsError(f"No such foz database: {foz_path}")

    profile_name = _DRIVER_PROFILE[driver]
    profile = config.load_profile_config(profile_name)
    env = config.profile_env(profile, session.root, force_nocache=True, cfg=cfg)

    raw_csv = session.subdir("stats") / f"_raw.{driver}.csv"
    result = foz_mod.replay_stats(foz_path, raw_csv, env, threads=threads, timeout_s=timeout_s)

    log_dir = session.subdir("logs")
    (log_dir / f"stats_replay_{driver}.stdout.log").write_text(result.stdout, encoding="utf-8")
    (log_dir / f"stats_replay_{driver}.stderr.log").write_text(result.stderr, encoding="utf-8")
    session.record_step(
        f"stats_replay_{driver}",
        ["fossilize-replay", "--enable-pipeline-stats", str(raw_csv), str(foz_path)],
        result.returncode,
        num_rows=result.num_rows,
        failure_count=result.failure_count,
    )
    session.use_profile(profile_name)

    if result.returncode not in (0, None) and result.num_rows == 0:
        raise StatsError(f"fossilize-replay produced no stats rows (returncode={result.returncode})")

    df = load_stats_csv(raw_csv, driver)
    out_csv = session.subdir("stats") / f"stats.{driver}.csv"
    df.to_csv(out_csv, index=False)
    session.record_artifact(out_csv, kind="stats_table", producer="tcc stats run", confidence="exact")
    return out_csv


def load_session_stats(session: Session, driver: str | None = None) -> pd.DataFrame:
    """Load previously-saved stats.<driver>.csv from a session. driver=None
    concatenates every stats.*.csv present."""
    stats_dir = session.subdir("stats")
    if driver:
        path = stats_dir / f"stats.{driver}.csv"
        if not path.is_file():
            raise StatsError(f"No stats table at {path}; run `tcc stats run --driver {driver}` first.")
        return pd.read_csv(path)

    paths = sorted(stats_dir.glob("stats.*.csv"))
    if not paths:
        raise StatsError(f"No stats tables in {stats_dir}; run `tcc stats run` first.")
    return pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)

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

from core import config
from core.errors import TccError
from shader_extractor import foz as foz_mod
from core.session import Session

_DRIVER_PROFILE = {"system": "baseline", "stock": "stock", "custom": "custom"}


class StatsError(TccError):
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
    # Wave size (32 vs 64). Must be tested BEFORE "subgroup size" could fall
    # through to anything else, and it is not optional: VOPD requires wave32,
    # so this is the strongest single covariate for dual-issue emission
    # (Remnant II: 17,482 wave64 shaders emitted VOPD zero times; 244 of 248
    # wave32 shaders emitted it). It used to sit unpromoted in `extra`, where
    # compare.py and mine.py could not see it at all.
    if "subgroup size" in h:
        return "subgroup_size"
    # M1-A: ACO's own per-stage counters. These are the thesis signals (VOPD
    # dual-issue, instruction mix, ACO's latency model) and compare.py needs
    # them as first-class numeric columns, not buried in the `extra` JSON.
    # Order matters: "vmem clause"/"smem clause" must lose to the clause check
    # below.
    if "clause" in h:
        return "vmem_clause" if "vmem" in h else ("smem_clause" if "smem" in h else None)
    if "inverse throughput" in h:
        return "inverse_throughput"
    if h == "instructions":
        return "instructions"
    if h == "latency":
        return "latency"
    if h == "copies":
        return "copies"
    if h == "branches":
        return "branches"
    if h == "valu":
        return "valu"
    if h == "salu":
        return "salu"
    if h == "vmem":
        return "vmem"
    if h == "smem":
        return "smem"
    if h == "vopd":
        return "vopd"
    return None


def _coerce(value: str):
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def load_stats_csv(csv_path: Path, driver: str,
                   provenance_map: dict[str, str] | None = None) -> pd.DataFrame:
    """Parse a raw fossilize-replay --enable-pipeline-stats CSV into the
    tidy row schema (see src/core/schemas/stats_table.schema.json).

    `provenance_map` (hash -> "run_recorded") comes from the merged corpus
    index. Merging every .foz for a game buys coverage but erases the file
    boundary that distinguished pipelines THIS machine compiled from Steam's
    downloaded pre-cache, so the distinction is re-attached here as a column.
    Hashes absent from the map are steam_precache.
    """
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
            if provenance_map is not None:
                row["provenance"] = provenance_map.get(str(row.get("pipeline_hash")), "steam_precache")
            row["extra"] = json.dumps(extra)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# run: profile resolution + fossilize-replay + parse + save
# ---------------------------------------------------------------------------


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
    foz_path = foz_mod.resolve_foz(session, explicit=foz_path)

    profile_name = _DRIVER_PROFILE[driver]
    profile = config.load_profile_config(profile_name)
    env = config.profile_env(profile, session.root, force_nocache=True, cfg=cfg)

    raw_csv = session.subdir("stats") / f"_raw.{driver}.csv"
    # run_recorded (inside replay_stats) writes the logs and the step record,
    # including the environment snapshot that names the ICD.
    result = foz_mod.replay_stats(
        session, f"stats_replay_{driver}", foz_path, raw_csv, env,
        threads=threads, timeout_s=timeout_s,
    )
    session.use_profile(profile_name)

    if result.returncode != 0 and result.num_rows == 0:
        raise StatsError(f"fossilize-replay produced no stats rows (returncode={result.returncode})")

    from shader_extractor import corpus as corpus_mod

    df = load_stats_csv(raw_csv, driver, provenance_map=corpus_mod.provenance_lookup(session.game))
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

"""Benchmark-run orchestration + MangoHud CSV summarization (Phase 6 slice).

`tcc bench run --game X --profile P` is the one-command capture flow:

  session (new or --session) -> foz snapshot before -> arm profile ->
  launch -> [human plays / triggers the benchmark per the game TOML] ->
  wait for exit -> foz snapshot after + delta -> register MangoHud CSVs ->
  bench_summary.json

Human steps are unavoidable for menu-triggered benchmarks and manual
scenes; everything around them is automated and recorded in the session.

MangoHud CSV layout (tolerant parser -- verified format for 0.6/0.7:
two system-info rows, then a column-header row containing "frametime",
then per-frame rows; frametime is in milliseconds).
"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

import pandas as pd

from launcher import arm as arm_mod
from core import config, util
from core.errors import TccError
from launcher import steam
from shader_extractor import foz
from core.session import Session


class BenchError(TccError):
    pass


# ---------------------------------------------------------------------------
# MangoHud CSV parsing / summary
# ---------------------------------------------------------------------------


# Frametimes slower than this are pauses, not rendered frames: menu-in,
# load screens, the between-run pause and the results screen that bracket a
# menu-triggered benchmark under autostart_log. A single 57-minute "frame"
# poisons every sum/mean/max stat while percentiles stay intact, so we drop
# them before aggregating and report how many were removed. 200 ms == a 5 fps
# floor; no real RDNA3 benchmark frame is that slow.
PAUSE_FRAMETIME_MS = 200.0


def parse_mangohud_csv(path: Path, pause_ms: float = PAUSE_FRAMETIME_MS) -> dict[str, Any]:
    """Summary metrics for one MangoHud log. Raises BenchError if the file
    doesn't look like a MangoHud log."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines[:10]) if "frametime" in line.lower()), None
    )
    if header_idx is None:
        raise BenchError(f"{path}: no 'frametime' column header found; not a MangoHud log?")

    df = pd.read_csv(path, skiprows=header_idx)
    df.columns = [c.strip().lower() for c in df.columns]
    if "frametime" not in df.columns or df.empty:
        raise BenchError(f"{path}: empty or missing frametime column")

    ft_raw = pd.to_numeric(df["frametime"], errors="coerce").dropna()
    if ft_raw.empty:
        raise BenchError(f"{path}: frametime column is non-numeric")

    ft = ft_raw[ft_raw <= pause_ms]
    dropped = int(len(ft_raw) - len(ft))
    if ft.empty:
        raise BenchError(
            f"{path}: every frametime exceeds the {pause_ms:.0f}ms pause floor; "
            "no rendered frames?"
        )

    meta: dict[str, str] = {}
    if header_idx >= 2:  # two system-info rows precede the column header
        keys = [k.strip() for k in lines[0].split(",")]
        vals = [v.strip() for v in lines[1].split(",")]
        meta = {k: v for k, v in zip(keys, vals) if k and v}

    duration_s = float(ft.sum()) / 1000.0
    summary = {
        "file": str(path),
        "frames": int(len(ft)),
        "raw_frames": int(len(ft_raw)),
        "pause_frames_dropped": dropped,
        "pause_floor_ms": pause_ms,
        "duration_s": round(duration_s, 2),
        "fps_avg": round(len(ft) / duration_s, 2) if duration_s > 0 else None,
        "fps_1pct_low": round(1000.0 / float(ft.quantile(0.99)), 2),
        "fps_01pct_low": round(1000.0 / float(ft.quantile(0.999)), 2),
        "frametime_ms": {
            "avg": round(float(ft.mean()), 3),
            "p50": round(float(ft.quantile(0.50)), 3),
            "p95": round(float(ft.quantile(0.95)), 3),
            "p99": round(float(ft.quantile(0.99)), 3),
            "p999": round(float(ft.quantile(0.999)), 3),
            "max": round(float(ft.max()), 3),
        },
        "system": meta,
    }
    return summary


def summarize(session: Session, only: list[Path] | None = None) -> Path:
    """Parse MangoHud CSVs in <session>/bench/ into bench/bench_summary.json.

    `only` scopes the summary to one run's files. Without it, a second bench in
    the same session folded the previous run's frames into the same summary
    with nothing marking which was which."""
    bench_dir = session.subdir("bench")
    # MangoHud writes a companion <name>_summary.csv next to each log; it has
    # no frametime rows, so it is metadata noise here, not a run.
    csvs = sorted(only) if only is not None else sorted(
        p for p in bench_dir.glob("*.csv") if not p.name.endswith("_summary.csv"))
    if not csvs:
        raise BenchError(f"No CSV files in {bench_dir}; was MangoHud logging toggled during the run?")

    runs = []
    errors = []
    for csv_path in csvs:
        try:
            runs.append(parse_mangohud_csv(csv_path))
            session.record_artifact(csv_path, kind="mangohud_csv", producer="mangohud", confidence="exact")
        except BenchError as exc:
            errors.append(str(exc))

    payload = {"session_id": session.session_id, "runs": runs, "parse_errors": errors}
    out_path = bench_dir / "bench_summary.json"
    util.write_json(out_path, payload)
    session.record_artifact(out_path, kind="bench_summary", producer="tcc bench summarize", confidence="exact")
    return out_path


# ---------------------------------------------------------------------------
# the one-command capture flow
# ---------------------------------------------------------------------------


def _pick_scene(game_cfg: config.GameConfig, scene: str | None) -> str:
    if scene:
        return scene
    for s in game_cfg.scenes:
        if s.kind == "benchmark":
            return s.id
    if game_cfg.scenes:
        return game_cfg.scenes[0].id
    return "adhoc"


def _print_instructions(game_cfg: config.GameConfig, scene_id: str) -> None:
    print("=" * 66)
    print(f"{game_cfg.game.name} -- scene '{scene_id}' "
          f"({game_cfg.benchmark.type}, trigger: {game_cfg.benchmark.trigger})")
    if game_cfg.benchmark.duration_hint_s:
        print(f"expected benchmark duration: ~{game_cfg.benchmark.duration_hint_s}s")
    text = game_cfg.benchmark.instructions.strip()
    if text:
        print("-" * 66)
        print(text)
    for s in game_cfg.scenes:
        if s.id == scene_id and s.protocol_doc:
            print(f"scene protocol: {s.protocol_doc}")
    print("=" * 66)


def run(
    game_slug: str,
    profile_name: str,
    session_ref: str | None = None,
    scene: str | None = None,
    wait: bool = True,
    do_foz: bool = True,
    ttl_min: int = arm_mod.DEFAULT_TTL_MIN,
    extra_args: str | None = None,
    exe_override: str | None = None,
    exe_match: str | None = None,
) -> Session:
    game_cfg = config.load_game_config(game_slug)
    scene_id = _pick_scene(game_cfg, scene)

    if session_ref:
        session = Session.load(session_ref)
    else:
        session = Session.create(game_slug, scene_id)
        print(f"session: {session.session_id}")
    print(f"session dir: {session.root}")

    # -- foz before ---------------------------------------------------------
    if do_foz and game_cfg.foz.cache_glob and game_cfg.game.appid is not None:
        try:
            copied = foz.snapshot(session, game_slug, "before")
            print(f"foz before: {len(copied)} file(s) snapshotted")
        except foz.FozError as exc:
            print(f"foz before: skipped ({exc})")
            session.add_note(f"foz before-snapshot skipped: {exc}")

    # -- arm ---------------------------------------------------------------
    # Benchmark-type games get autostarted MangoHud logging (hotkeys are
    # unreliable under Wayland/pressure-vessel); manual scenes stay
    # toggle-only (Shift_L+F2) so free play isn't logged wall-to-wall.
    autostart = game_cfg.benchmark.type in ("builtin", "standalone", "cli")
    payload = arm_mod.arm(
        profile_name,
        session=session,
        game=game_slug,
        ttl_min=ttl_min,
        exe_override=exe_override,
        exe_match=exe_match,
        mangohud_autostart=autostart,
    )
    print(f"armed: profile={payload['profile']} driver={payload['driver']} "
          f"one_shot={payload['one_shot']} ttl_min={ttl_min}")

    _print_instructions(game_cfg, scene_id)

    # -- launch --------------------------------------------------------------
    args = shlex.split(extra_args) if extra_args else []
    started_epoch = time.time()
    proc = steam.launch(game_cfg, extra_args=args)
    session.record_step("launch", ["steam-or-wrapper", game_slug, *args], 0)

    if game_cfg.game.kind == "steam":
        print(f"launched via steam -applaunch {game_cfg.game.appid}; "
              "waiting for the game process (Ctrl-C to stop waiting; the "
              "session stays usable -- finish later with `tcc bench summarize`).")
        if not wait:
            print("--no-wait: run the benchmark, quit the game, then run:\n"
                  f"  tcc foz snapshot --session {session.session_id} --label after\n"
                  f"  tcc foz delta --session {session.session_id}\n"
                  f"  tcc bench summarize --session {session.session_id}")
            return session
        result = steam.wait_for_exit(game_cfg.game.appid)
        session.record_step("wait_for_exit", [str(game_cfg.game.appid)], 0, **result)
        if not result["appeared"]:
            print("warning: game process never appeared (launch canceled? Steam "
                  "not running?); continuing with post-run collection anyway.")
        else:
            print(f"game exited after {result['elapsed_s']}s")
    elif proc is not None:
        returncode = proc.wait()
        session.record_step("native_run", [game_slug, *args], returncode)
        print(f"exited with code {returncode}")

    # -- post-run collection ---------------------------------------------------
    if do_foz and game_cfg.foz.cache_glob and game_cfg.game.appid is not None:
        try:
            copied = foz.snapshot(session, game_slug, "after")
            print(f"foz after: {len(copied)} file(s) snapshotted")
            counts = foz.delta(session)
            print("foz delta (new): " + ", ".join(f"{k}={v}" for k, v in counts["new"].items()))
            print("foz delta (run-created): "
                  + ", ".join(f"{k}={v}" for k, v in counts["run_created"].items()))
        except foz.FozError as exc:
            print(f"foz after/delta: skipped ({exc})")
            session.add_note(f"foz after/delta skipped: {exc}")

    new_csvs = [p for p in sorted(session.subdir("bench").glob("*.csv"))
                if p.stat().st_mtime >= started_epoch - 5]
    if new_csvs:
        try:
            out = summarize(session, only=new_csvs)
            print(f"bench summary: {out}")
        except BenchError as exc:
            print(f"bench summary: {exc}")
    else:
        print("no new MangoHud CSVs in bench/ (profile without mangohud, or "
              "logging never toggled).")

    leftover = arm_mod.show()
    if leftover and not leftover.get("stale"):
        print("note: armed profile was NOT consumed (game bypassed the wrapper? "
              "launch options not set?). `tcc disarm` to clear it.")

    print(f"\nnext: tcc stats run --session {session.session_id} --driver stock")
    return session

"""tcc command-line interface.

Fully implemented: --version, doctor, session (new/list/show/note/close)
from Phase 1; foz (snapshot/delta/extract/import), stats (run/show), and
mine from Phase 2. Every other subcommand from plan §4 exists as a real
parser (so --help and scripts written against the final surface both work)
but its handler prints "not implemented yet" with the phase that will
implement it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core import __version__
from launcher import arm as arm_mod
from benchmark import game_bench as bench_mod
from core import config as config_mod
from shader_extractor import foz as foz_mod
from analysis import mine as mine_mod
from core import session as session_mod
from analysis import stats as stats_mod
from launcher import steam as steam_mod
from core import toolchain


def _not_implemented(command: str, phase: int) -> int:
    print(f"tcc {command}: not implemented yet (Phase {phase})", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = toolchain.doctor()
    if args.json:
        print(json.dumps([vars(c) for c in checks], indent=2))
    else:
        for c in checks:
            line = f"[{c.status:>7}] {c.name}: {c.detail}"
            if c.remedy:
                line += f"\n           remedy: {c.remedy}"
            print(line)
    return 1 if any(c.status == "missing" for c in checks) else 0


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


def cmd_session_new(args: argparse.Namespace) -> int:
    session = session_mod.Session.create(args.game, args.scene, note=args.note)
    print(session.session_id)
    return 0


def cmd_session_list(args: argparse.Namespace) -> int:
    rows = session_mod.list_sessions(game=args.game)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['session_id']}  [{row['status']}]  {row['game']}/{row['scene']}")
    return 0


def cmd_session_show(args: argparse.Namespace) -> int:
    try:
        session = session_mod.Session.load(args.ref)
    except session_mod.SessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        manifest = session.to_manifest()
        manifest["artifacts"] = session.artifacts
        print(json.dumps(manifest, indent=2))
    else:
        print(f"session_id: {session.session_id}")
        print(f"game/scene: {session.game}/{session.scene}")
        print(f"status:     {session.status}")
        print(f"created_at: {session.created_at}")
        print(f"root:       {session.root}")
        print(f"steps={len(session.steps)} notes={len(session.notes)} artifacts={len(session.artifacts)}")
    return 0


def cmd_session_note(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.ref)
    session.add_note(args.text)
    return 0


def cmd_session_close(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.ref)
    session.close()
    print(f"closed {session.session_id}")
    return 0


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------


def _add_session_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_session = sub.add_parser("session", help="session lifecycle")
    session_sub = p_session.add_subparsers(dest="session_action", required=True)

    p = session_sub.add_parser("new", parents=[common])
    p.add_argument("--game", required=True)
    p.add_argument("--scene", required=True)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_session_new)

    p = session_sub.add_parser("list", parents=[common])
    p.add_argument("--game", default=None)
    p.set_defaults(func=cmd_session_list)

    p = session_sub.add_parser("show", parents=[common])
    p.add_argument("ref", help="full session id, unique substring, or @last")
    p.set_defaults(func=cmd_session_show)

    p = session_sub.add_parser("note", parents=[common])
    p.add_argument("ref")
    p.add_argument("text")
    p.set_defaults(func=cmd_session_note)

    p = session_sub.add_parser("close", parents=[common])
    p.add_argument("ref")
    p.set_defaults(func=cmd_session_close)


def cmd_foz_snapshot(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    for path in foz_mod.snapshot(session, session.game, args.label):
        print(path)
    return 0


def cmd_foz_delta(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    counts = foz_mod.delta(session)
    if args.json:
        print(json.dumps(counts, indent=2))
    else:
        for name in counts["new"]:
            print(f"{name}: {counts['new'][name]} new hash(es), "
                  f"{counts['run_created'][name]} created by this run")
    return 0


def cmd_foz_extract(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    hashes = None
    if args.hashes:
        hashes = [line.strip() for line in Path(args.hashes).read_text().splitlines() if line.strip()]
    print(foz_mod.extract(session, hashes=hashes))
    return 0


def cmd_foz_import(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    print(foz_mod.import_foz(session, args.game, Path(args.path)))
    return 0


def cmd_stats_run(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    foz_path = Path(args.foz) if args.foz else None
    print(stats_mod.run(session, args.driver, foz_path=foz_path))
    return 0


def cmd_stats_show(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    df = stats_mod.load_session_stats(session, driver=args.driver)
    if args.sort:
        df = df.sort_values(args.sort, ascending=False)
    if args.top:
        df = df.head(args.top)
    print(df.to_json(orient="records", indent=2) if args.json else df.to_string(index=False))
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    top_df = mine_mod.rank(session, driver=args.driver, top=args.top, rank_by=args.rank)
    print(top_df.to_json(orient="records", indent=2) if args.json else top_df.to_string(index=False))
    return 0


def _add_foz_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_foz = sub.add_parser("foz", parents=[common])
    foz_sub = p_foz.add_subparsers(dest="foz_action", required=True)

    p = foz_sub.add_parser("snapshot", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--label", choices=["before", "after"], required=True)
    p.set_defaults(func=cmd_foz_snapshot)

    p = foz_sub.add_parser("delta", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=cmd_foz_delta)

    p = foz_sub.add_parser("extract", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--hashes", default=None, help="text file, one pipeline hash per line")
    p.set_defaults(func=cmd_foz_extract)

    p = foz_sub.add_parser("import", parents=[common])
    p.add_argument("--session", default="@last")
    p.add_argument("--game", required=True)
    p.add_argument("path")
    p.set_defaults(func=cmd_foz_import)


def _add_stats_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_stats = sub.add_parser("stats", parents=[common])
    stats_sub = p_stats.add_subparsers(dest="stats_action", required=True)

    p = stats_sub.add_parser("run", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", choices=["system", "stock", "custom"], required=True)
    p.add_argument("--foz", default=None)
    p.set_defaults(func=cmd_stats_run)

    p = stats_sub.add_parser("show", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", default=None)
    p.add_argument("--sort", default=None)
    p.add_argument("--top", type=int, default=None)
    p.set_defaults(func=cmd_stats_show)


def _add_mine_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_mine = sub.add_parser("mine", parents=[common])
    p_mine.add_argument("--session", required=True)
    p_mine.add_argument("--driver", default=None)
    p_mine.add_argument("--top", type=int, default=25)
    p_mine.add_argument("--rank", choices=["waves", "vgprs", "spill", "code_size", "score"], default="score")
    p_mine.set_defaults(func=cmd_mine)


def cmd_compare(args: argparse.Namespace) -> int:
    """Metric 1: diff two stats tables. --a/--b are driver labels resolved
    inside the session's stats/ dir, or explicit CSV paths."""
    from pathlib import Path

    from analysis import compare as compare_mod

    session = session_mod.Session.load(args.session) if args.session else None

    def resolve(spec: str) -> tuple[Path, str]:
        p = Path(spec)
        if p.is_file():
            return p, p.stem.replace("stats.", "")
        if session is None:
            raise SystemExit(f"error: '{spec}' is not a file and no --session given")
        return session.subdir("stats") / f"stats.{spec}.csv", spec

    path_a, label_a = resolve(args.a)
    path_b, label_b = resolve(args.b)
    out_dir = Path(args.out) if args.out else (
        session.subdir("stats") if session else Path.cwd())

    result = compare_mod.run(session, path_a, path_b, label_a, label_b, out_dir)
    print(compare_mod.render_markdown(result, label_a, label_b))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Copy recorded pipeline caches out of the Steam shadercache into data/foz/."""
    from shader_extractor import collect as collect_mod

    slugs = args.game.split(",") if args.game else None
    result = collect_mod.collect_all(slugs=slugs, skip_whitelist=args.skip_whitelist)

    total = 0
    for slug, man in sorted(result["collected"].items()):
        c = man["counts"]
        total += man["total_bytes"]
        print(f"{slug:18} {man['total_bytes']/1e6:9.1f} MB  "
              f"run={c['run_recorded']} precache={c['steam_precache']} whitelist={c['whitelist']}")
    for slug, why in sorted(result["skipped"].items()):
        print(f"{slug:18} SKIPPED  {why}")
    print(f"{'TOTAL':18} {total/1e9:9.2f} GB collected, verified by sha256")
    return 0


def _add_collect_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("collect", parents=[common],
                       help="copy Steam-recorded pipeline caches into data/foz/<game>/")
    p.add_argument("--game", default=None, help="comma-separated slugs (default: all configured)")
    p.add_argument("--skip-whitelist", action="store_true",
                   help="omit Valve's steam_pipeline_cache_whitelist.foz files")
    p.set_defaults(func=cmd_collect)


def cmd_arm(args: argparse.Namespace) -> int:
    if args.arm_action == "show":
        payload = arm_mod.show()
        if payload is None:
            print("nothing armed")
            return 0
        print(json.dumps(payload, indent=2))
        return 0
    if not args.profile:
        print("error: --profile is required (or use `tcc arm show`)", file=sys.stderr)
        return 2
    session = session_mod.Session.load(args.session) if args.session else None
    extra_env = dict(kv.split("=", 1) for kv in (args.env or []))
    payload = arm_mod.arm(
        args.profile,
        session=session,
        game=args.game,
        ttl_min=args.ttl,
        sticky=args.sticky,
        exe_override=args.exe_override,
        exe_match=args.exe_match,
        extra_env=extra_env or None,
    )
    print(f"armed profile={payload['profile']} driver={payload['driver']} "
          f"game={payload['game'] or 'any'} one_shot={payload['one_shot']} "
          f"expires_epoch={payload['expires_epoch']}")
    return 0


def cmd_disarm(args: argparse.Namespace) -> int:
    print("disarmed" if arm_mod.disarm() else "nothing was armed")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session) if args.session else None
    game_slug = args.game or (session.game if session else None)
    if not game_slug:
        print("error: pass --game or --session", file=sys.stderr)
        return 2
    game_cfg = config_mod.load_game_config(game_slug)
    import shlex

    extra = shlex.split(args.args) if args.args else []
    proc = steam_mod.launch(game_cfg, extra_args=extra)
    if session:
        session.record_step("launch", ["tcc", "launch", game_slug, *extra], 0)
    if game_cfg.game.kind == "steam":
        print(f"launched via steam -applaunch {game_cfg.game.appid}")
        if args.wait:
            result = steam_mod.wait_for_exit(game_cfg.game.appid)
            if session:
                session.record_step("wait_for_exit", [str(game_cfg.game.appid)], 0, **result)
            print(f"appeared={result['appeared']} exited={result['exited']} "
                  f"elapsed_s={result['elapsed_s']}")
    elif proc is not None and args.wait:
        print(f"exited with code {proc.wait()}")
    return 0


def cmd_bench_run(args: argparse.Namespace) -> int:
    bench_mod.run(
        args.game,
        args.profile,
        session_ref=args.session,
        scene=args.scene,
        wait=not args.no_wait,
        do_foz=not args.no_foz,
        ttl_min=args.ttl,
        extra_args=args.args,
        exe_override=args.exe_override,
        exe_match=args.exe_match,
    )
    return 0


def cmd_bench_summarize(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    out = bench_mod.summarize(session)
    print(out)
    if args.json:
        print(Path(out).read_text(encoding="utf-8"))
    return 0


def _add_arm_launch_parsers(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_arm = sub.add_parser("arm", parents=[common], help="arm a profile for the next launch")
    p_arm.add_argument("--session", default=None)
    p_arm.add_argument("--profile", default=None)
    p_arm.add_argument("--game", default=None, help="game slug (sets TCC_APPID guard)")
    p_arm.add_argument("--ttl", type=int, default=240, help="minutes until the armed profile goes stale")
    p_arm.add_argument("--sticky", action="store_true", help="survive multiple launches (default: one-shot)")
    p_arm.add_argument("--exe-override", default=None, help="substitute exe in %%command%% (e.g. Metro Benchmark.exe)")
    p_arm.add_argument("--exe-match", default=None, help="original exe basename to replace")
    p_arm.add_argument("--env", action="append", default=None, metavar="KEY=VAL")
    arm_sub = p_arm.add_subparsers(dest="arm_action")
    arm_sub.add_parser("show", parents=[common]).set_defaults(func=cmd_arm, arm_action="show")
    p_arm.set_defaults(func=cmd_arm, arm_action=None)

    sub.add_parser("disarm", parents=[common]).set_defaults(func=cmd_disarm)

    p_launch = sub.add_parser("launch", parents=[common], help="launch a game (armed profile applies via wrapper)")
    p_launch.add_argument("--session", default=None)
    p_launch.add_argument("--game", default=None)
    p_launch.add_argument("--wait", action="store_true")
    p_launch.add_argument("--args", default=None)
    p_launch.set_defaults(func=cmd_launch)


def _add_bench_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_bench = sub.add_parser("bench", parents=[common], help="benchmark capture flow")
    bench_sub = p_bench.add_subparsers(dest="bench_action", required=True)

    p = bench_sub.add_parser("run", parents=[common])
    p.add_argument("--game", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--session", default=None, help="reuse an existing session (default: create one)")
    p.add_argument("--scene", default=None)
    p.add_argument("--ttl", type=int, default=240)
    p.add_argument("--args", default=None, help="extra launch args")
    p.add_argument("--exe-override", default=None)
    p.add_argument("--exe-match", default=None)
    p.add_argument("--no-wait", action="store_true", help="don't block on game exit")
    p.add_argument("--no-foz", action="store_true", help="skip foz before/after snapshots")
    p.set_defaults(func=cmd_bench_run)

    p = bench_sub.add_parser("summarize", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=cmd_bench_summarize)


def _add_stub_commands(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Parsers for every subcommand in plan §4 that isn't implemented yet.
    Each prints "not implemented yet (Phase N)" and exits 2."""

    def stub(name: str, phase: int):
        return lambda args: _not_implemented(name, phase)

    # isa -- Phase 4 (isa.py, hazards port) ---------------------------------
    p_isa = sub.add_parser("isa", parents=[common])
    isa_sub = p_isa.add_subparsers(dest="isa_action", required=True)
    p = isa_sub.add_parser("extract", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--hash", action="append", default=None)
    p.add_argument("--top", type=int, default=None)
    p.set_defaults(func=stub("isa extract", 4))
    p = isa_sub.add_parser("metrics", parents=[common])
    p.add_argument("--deep", action="store_true")
    p.set_defaults(func=stub("isa metrics", 4))
    p = isa_sub.add_parser("diff", parents=[common])
    p.add_argument("--hash", required=True)
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.set_defaults(func=stub("isa diff", 4))

    # rga -- Phase 4 (rga.py) ------------------------------------------------
    p_rga = sub.add_parser("rga", parents=[common])
    rga_sub = p_rga.add_subparsers(dest="rga_action", required=True)
    p = rga_sub.add_parser("run", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--hash", default=None)
    p.add_argument("--top", type=int, default=None)
    p.set_defaults(func=stub("rga run", 4))

    p_compare = sub.add_parser("compare", parents=[common],
                               help="diff two stats tables (Metric 1)")
    p_compare.add_argument("--session", default=None)
    p_compare.add_argument("--a", required=True, help="driver label or path to stats CSV")
    p_compare.add_argument("--b", required=True, help="driver label or path to stats CSV")
    p_compare.add_argument("--out", default=None)
    p_compare.set_defaults(func=cmd_compare)

    # capture -- Phase 6 (renderdoc_ctl.py) -----------------------------------
    p_capture = sub.add_parser("capture", parents=[common])
    capture_sub = p_capture.add_subparsers(dest="capture_action", required=True)
    p = capture_sub.add_parser("rdc", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--frame", type=int, default=None)
    p.add_argument("--after", type=int, default=None)
    p.add_argument("--collect-only", action="store_true")
    p.set_defaults(func=stub("capture rdc", 6))
    p = capture_sub.add_parser("sqtt", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=stub("capture sqtt", 6))

    # lab -- Phase 5 (shaderlab) ----------------------------------------------
    p_lab = sub.add_parser("lab", parents=[common])
    lab_sub = p_lab.add_subparsers(dest="lab_action", required=True)
    lab_sub.add_parser("list", parents=[common]).set_defaults(func=stub("lab list", 5))
    p = lab_sub.add_parser("new", parents=[common])
    p.add_argument("name")
    p.set_defaults(func=stub("lab new", 5))
    lab_sub.add_parser("build", parents=[common]).set_defaults(func=stub("lab build", 5))
    p = lab_sub.add_parser("run", parents=[common])
    p.add_argument("--exp", required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--vopd", choices=["on", "off"], default=None)
    p.set_defaults(func=stub("lab run", 5))
    p = lab_sub.add_parser("isa", parents=[common])
    p.add_argument("--exp", required=True)
    p.add_argument("--driver", required=True)
    p.set_defaults(func=stub("lab isa", 5))
    p = lab_sub.add_parser("compare", parents=[common])
    p.add_argument("--exp", required=True)
    p.add_argument("--drivers", default=None)
    p.set_defaults(func=stub("lab compare", 5))

    # report -- Phase 7 (report.py) -------------------------------------------
    p_report = sub.add_parser("report", parents=[common])
    report_sub = p_report.add_subparsers(dest="report_action", required=True)
    p = report_sub.add_parser("session", parents=[common])
    p.add_argument("session")
    p.add_argument("--out", default=None)
    p.set_defaults(func=stub("report session", 7))
    p = report_sub.add_parser("cohort", parents=[common])
    p.add_argument("--games", default=None)
    p.set_defaults(func=stub("report cohort", 7))

    # mesa -- Phase 4 (rebuild cadence lines up with the stock/custom compare
    # workflow: rebuild custom ACO, then `tcc compare` to check the delta) ----
    p_mesa = sub.add_parser("mesa", parents=[common])
    mesa_sub = p_mesa.add_subparsers(dest="mesa_action", required=True)
    p = mesa_sub.add_parser("build", parents=[common])
    p.add_argument("--variant", choices=["stock", "custom"], required=True)
    p.set_defaults(func=stub("mesa build", 4))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    parser = argparse.ArgumentParser(prog="tcc")
    parser.add_argument("--version", action="version", version=f"tcc {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_doctor = sub.add_parser("doctor", parents=[common], help="environment/toolchain health check")
    p_doctor.set_defaults(func=cmd_doctor)

    _add_session_parser(sub, common)
    _add_foz_parser(sub, common)
    _add_stats_parser(sub, common)
    _add_mine_parser(sub, common)
    _add_collect_parser(sub, common)
    _add_arm_launch_parsers(sub, common)
    _add_bench_parser(sub, common)
    _add_stub_commands(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except (
        foz_mod.FozError,
        stats_mod.StatsError,
        session_mod.SessionError,
        arm_mod.ArmError,
        bench_mod.BenchError,
        steam_mod.SteamError,
        config_mod.ConfigError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

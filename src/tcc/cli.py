"""tcc command-line interface.

Fully implemented in Phase 1: --version, doctor, session (new/list/show/note/close).
Every other subcommand from plan §4 exists as a real parser (so --help and
scripts written against the final surface both work) but its handler prints
"not implemented yet" with the phase that will implement it.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, session as session_mod, toolchain


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


def _add_stub_commands(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Parsers for every subcommand in plan §4 that isn't implemented yet.
    Each prints "not implemented yet (Phase N)" and exits 2."""

    def stub(name: str, phase: int):
        return lambda args: _not_implemented(name, phase)

    # arm / disarm / launch -- Phase 3 (arm.py, steam.py, wrapper) ----------
    p_arm = sub.add_parser("arm", parents=[common])
    p_arm.add_argument("--session")
    p_arm.add_argument("--profile")
    p_arm.add_argument("--ttl", type=int, default=240)
    p_arm.add_argument("--sticky", action="store_true")
    arm_sub = p_arm.add_subparsers(dest="arm_action")
    arm_sub.add_parser("show", parents=[common]).set_defaults(func=stub("arm show", 3))
    p_arm.set_defaults(func=stub("arm", 3))

    sub.add_parser("disarm", parents=[common]).set_defaults(func=stub("disarm", 3))

    p_launch = sub.add_parser("launch", parents=[common])
    p_launch.add_argument("--session")
    p_launch.add_argument("--wait", action="store_true")
    p_launch.add_argument("--args", default=None)
    p_launch.set_defaults(func=stub("launch", 3))

    # foz -- Phase 2 (foz.py) -----------------------------------------------
    p_foz = sub.add_parser("foz", parents=[common])
    foz_sub = p_foz.add_subparsers(dest="foz_action", required=True)
    p = foz_sub.add_parser("snapshot", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--label", choices=["before", "after"], required=True)
    p.set_defaults(func=stub("foz snapshot", 2))
    p = foz_sub.add_parser("delta", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=stub("foz delta", 2))
    p = foz_sub.add_parser("extract", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--hashes", default=None)
    p.set_defaults(func=stub("foz extract", 2))
    p = foz_sub.add_parser("import", parents=[common])
    p.add_argument("--game", required=True)
    p.add_argument("path")
    p.set_defaults(func=stub("foz import", 2))

    # stats -- Phase 2 (stats.py) -----------------------------------------
    p_stats = sub.add_parser("stats", parents=[common])
    stats_sub = p_stats.add_subparsers(dest="stats_action", required=True)
    p = stats_sub.add_parser("run", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", choices=["system", "stock", "custom"], required=True)
    p.add_argument("--foz", default=None)
    p.set_defaults(func=stub("stats run", 2))
    p = stats_sub.add_parser("show", parents=[common])
    p.add_argument("--sort", default=None)
    p.add_argument("--top", type=int, default=None)
    p.set_defaults(func=stub("stats show", 2))

    # mine -- Phase 2 (mine.py) --------------------------------------------
    p_mine = sub.add_parser("mine", parents=[common])
    p_mine.add_argument("--session", required=True)
    p_mine.add_argument("--driver", default=None)
    p_mine.add_argument("--top", type=int, default=25)
    p_mine.add_argument("--rank", choices=["waves", "vgprs", "spill", "code_size", "score"], default="score")
    p_mine.set_defaults(func=stub("mine", 2))

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

    # compare -- Phase 4 (compare.py) -----------------------------------------
    p_compare = sub.add_parser("compare", parents=[common])
    p_compare.add_argument("--session", required=True)
    p_compare.add_argument("--a", required=True)
    p_compare.add_argument("--b", required=True)
    p_compare.add_argument("--llvm", action="store_true")
    p_compare.add_argument("--out", default=None)
    p_compare.set_defaults(func=stub("compare", 4))

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

    # bench -- Phase 6 (bench.py) --------------------------------------------
    p_bench = sub.add_parser("bench", parents=[common])
    bench_sub = p_bench.add_subparsers(dest="bench_action", required=True)
    p = bench_sub.add_parser("run", parents=[common])
    p.add_argument("--game", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.set_defaults(func=stub("bench run", 6))
    p = bench_sub.add_parser("summarize", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=stub("bench summarize", 6))

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
    _add_stub_commands(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""tcc command-line interface.

Every subcommand here is implemented. Planned-but-unwritten commands used to
exist as stub parsers that printed "not implemented yet"; they were deleted
2026-08-03 because `--help` advertising six command groups that all exit 2 is
worse than a short help listing. The planned surface lives in docs/, not in
argparse.

Handlers stay thin: parse, call one module function, print. Logic belongs in
the package that owns the concept. Every user-facing failure is a TccError and
is turned into one `error: ...` line by main().
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from core import __version__
from core.errors import TccError
from launcher import arm as arm_mod
from benchmark import game_bench as bench_mod
from benchmark import ledger as ledger_mod
from benchmark import shaderbench as sb_mod
from core import config as config_mod
from shader_extractor import collect as collect_mod
from shader_extractor import corpus as corpus_mod
from shader_extractor import foz as foz_mod
from analysis import chart as chart_mod
from analysis import compare as compare_mod
from analysis import isa as isa_mod
from analysis import mine as mine_mod
from core import session as session_mod
from analysis import stats as stats_mod
from launcher import steam as steam_mod
from core import toolchain


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
    counts = foz_mod.delta(session, before=args.before, after=args.after)
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
    p.add_argument("--label", required=True,
                   help="phase name: before/after, or menu/loaded/done for phased capture")
    p.set_defaults(func=cmd_foz_snapshot)

    p = foz_sub.add_parser("delta", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--before", default="before", help="earlier phase label")
    p.add_argument("--after", default="after", help="later phase label")
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


_STATUS_LABEL = {
    "current": "CURRENT",
    "archived": "ARCHIVED",
    "no_cache": "NO CACHE",
    "stale": "STALE",
    "not_collected": "NOT COLLECTED",
    "error": "ERROR",
}


def _human_bytes(n: int) -> str:
    if n <= 0:
        return "--"
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} B"


def cmd_collect_check(args: argparse.Namespace) -> int:
    """Report which games still hold shader data that is not safely copied.
    Exit 1 if any game would lose data on uninstall, so this can gate a script."""
    slugs = args.game.split(",") if args.game else None
    rows = collect_mod.check_all(slugs=slugs, deep=args.deep)

    if args.json:
        print(json.dumps([vars(r) for r in rows], indent=2))
    else:
        print(f"{'slug':<20} {'installed':<10} {'collected':>10} {'live':>10}  status")
        for r in sorted(rows, key=lambda r: (r.safe_to_uninstall, r.slug)):
            print(f"{r.slug:<20} {'yes' if r.installed else 'no':<10} "
                  f"{_human_bytes(r.collected_bytes):>10} {_human_bytes(r.live_bytes):>10}  "
                  f"{_STATUS_LABEL[r.status]}")

    at_risk = [r for r in rows if not r.safe_to_uninstall and r.status != "error"]
    errors = [r for r in rows if r.status == "error"]
    if not args.json:
        counts = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        print("\n" + " · ".join(f"{n} {_STATUS_LABEL[s].lower()}" for s, n in sorted(counts.items())))
        for r in errors:
            print(f"  {r.slug}: {r.detail}")
        if at_risk:
            print(f"\n⚠ {len(at_risk)} game(s) hold shader data that is NOT saved — do not uninstall:")
            for r in at_risk:
                print(f"    {r.slug:<20} {r.detail}")
            print(f"\n  tcc collect --game {','.join(r.slug for r in at_risk)}")
        else:
            print("\n✅ every live shadercache is collected — safe to uninstall any of them.")
    return 1 if at_risk else 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Copy recorded pipeline caches out of the Steam shadercache into data/foz/."""
    if args.check:
        return cmd_collect_check(args)

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


def cmd_corpus_build(args: argparse.Namespace) -> int:
    """Merge every collected .foz for a game into one deduplicated corpus."""
    slugs = args.game.split(",") if args.game else [
        d.name for d in sorted((config_mod.load_tcc_config().paths.data_dir / "foz").iterdir())
        if d.is_dir()
    ]
    results, failures = [], {}
    for slug in slugs:
        try:
            results.append(corpus_mod.build(slug, force=args.force))
        except corpus_mod.CorpusError as exc:
            failures[slug] = str(exc)

    for r in results:
        merged, best = r.gain("graphics")
        extra = merged - best
        pct = f"+{extra / best * 100:.1f}%" if best else "n/a"
        print(f"{r.slug:<18} {r.source_count} file(s) -> {merged:,} graphics "
              f"(best single {best:,}, {pct}) {r.foz_path}")
    for slug, why in sorted(failures.items()):
        print(f"{slug:<18} SKIPPED  {why}", file=sys.stderr)
    return 1 if failures and not results else 0


def cmd_corpus_show(args: argparse.Namespace) -> int:
    rows = corpus_mod.list_built()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no corpus built yet; run `tcc corpus build --game <slug>`")
        return 0
    print(f"{'slug':<18} {'size':>9} {'graphics':>10} {'run_rec':>9} {'precache':>9}  built")
    for r in rows:
        g = r["counts"].get("graphics", {})
        print(f"{r['slug']:<18} {r['size_bytes'] / 1e6:>8.1f}M {g.get('total', 0):>10,} "
              f"{g.get('run_recorded', 0):>9,} {g.get('steam_precache', 0):>9,}  {r['built_at']}")
    return 0


def _add_corpus_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_corpus = sub.add_parser("corpus", parents=[common],
                              help="merge all collected .foz per game into one database")
    corpus_sub = p_corpus.add_subparsers(dest="corpus_action", required=True)

    p = corpus_sub.add_parser("build", parents=[common])
    p.add_argument("--game", default=None, help="comma-separated slugs (default: everything collected)")
    p.add_argument("--force", action="store_true", help="rebuild an existing corpus")
    p.set_defaults(func=cmd_corpus_build)

    p = corpus_sub.add_parser("show", parents=[common])
    p.set_defaults(func=cmd_corpus_show)


def _add_collect_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("collect", parents=[common],
                       help="copy Steam-recorded pipeline caches into data/foz/<game>/")
    p.add_argument("--game", default=None, help="comma-separated slugs (default: all configured)")
    p.add_argument("--skip-whitelist", action="store_true",
                   help="omit Valve's steam_pipeline_cache_whitelist.foz files")
    p.add_argument("--check", action="store_true",
                   help="don't copy: report which games still hold unsaved shader data "
                        "(exit 1 if any). Run before uninstalling anything.")
    p.add_argument("--deep", action="store_true",
                   help="with --check, re-hash every live file instead of comparing sizes "
                        "(reads the whole live cache; slow)")
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

    p = bench_sub.add_parser("shaders", parents=[common],
                             help="Metric 3: run the corpus as a GPU workload (native-Vulkan titles)")
    p.add_argument("--session", required=True)
    p.add_argument("--game", required=True)
    p.add_argument("--compilers", default="stock,custom", help="comma-separated driver labels")
    p.add_argument("--top", type=int, default=None, help="limit to N pipelines")
    p.add_argument("--warmup", type=int, default=50)
    p.add_argument("--iterations", type=int, default=200)
    p.add_argument("--repetitions", type=int, default=4)
    p.add_argument("--invocations", type=int, default=1 << 20)
    p.add_argument("--arena-mb", type=int, default=256)
    p.add_argument("--batch", type=int, default=25,
                   help="pipelines per process; a GPU fault costs one batch, not the run")
    p.set_defaults(func=cmd_bench_shaders)

    p = bench_sub.add_parser("summarize", parents=[common])
    p.add_argument("--session", required=True)
    p.set_defaults(func=cmd_bench_summarize)


def cmd_isa_extract(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    if args.hash:
        hashes = list(args.hash)
    else:
        top = mine_mod.rank(session, driver=args.driver, top=args.top, rank_by="score")
        hashes = list(dict.fromkeys(top["pipeline_hash"].astype(str)))
    print(f"disassembling {len(hashes)} shader(s) under {args.driver}...")
    print(isa_mod.extract(session, args.driver, hashes))
    return 0


def cmd_isa_metrics(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    rows = isa_mod.parse_dir(session.subdir("isa") / args.driver)
    summary = isa_mod.summarize(rows)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for k, v in summary.items():
            print(f"{k:24} {v}")
    return 0


def cmd_isa_diff(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    out = isa_mod.diff_dirs(session, args.a, args.b)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"compared {payload['shaders_compared']} shader(s); "
          f"{payload['shaders_changed']} changed instruction mix")
    print(f"⚠️  {payload['caveat']}")
    print(out)
    return 0


def cmd_chart(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    out = chart_mod.generate(session, driver=args.driver)
    print(out)
    print("open it in a browser: weights, terms and grouping are all client-side, "
          "so re-scoring never needs another replay.")
    return 0


def cmd_bench_shaders(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    opts = sb_mod.BenchOptions(
        warmup=args.warmup, iterations=args.iterations, repetitions=args.repetitions,
        invocations=args.invocations, arena_mb=args.arena_mb, batch=args.batch)
    out = sb_mod.run(session, args.game, args.compilers.split(","), opts, top=args.top)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    for d, info in payload["drivers"].items():
        print(f"{d:8} coverage={info['coverage']} batches_faulted={info['batches_faulted']}")
    if payload["deltas"]:
        pcts = [x["delta_pct"] for x in payload["deltas"]]
        print(f"delta over {len(pcts)} stable shader(s): "
              f"mean {sum(pcts)/len(pcts):+.3f}%  median {sorted(pcts)[len(pcts)//2]:+.3f}%")
    else:
        print("no stable shader ran under every driver — see coverage above")
    print(f"⚠️  {payload['caveat']}")
    print(out)
    return 0


def cmd_ledger_add(args: argparse.Namespace) -> int:
    session = session_mod.Session.load(args.session)
    stats_dir = session.subdir("stats")
    cmp_json = next(iter(sorted(stats_dir.glob("compare.*.json"))), None)
    sb_json = session.subdir("bench") / f"shaderbench.{args.game}.json"
    bench_json = session.subdir("bench") / "bench_summary.json"
    row = ledger_mod.build_row(session, args.game, compare_json=cmp_json,
                               shaderbench_json=sb_json, bench_summary=bench_json,
                               notes=args.note or "")
    print(ledger_mod.append(row))
    return 0


def cmd_ledger_show(args: argparse.Namespace) -> int:
    rows = ledger_mod.load()
    print(json.dumps(rows, indent=2) if args.json else ledger_mod.render(rows))
    return 0


def _add_ledger_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_l = sub.add_parser("ledger", parents=[common],
                         help="one row per (workload, compiler revision)")
    ls = p_l.add_subparsers(dest="ledger_action", required=True)
    p = ls.add_parser("add", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--game", required=True)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_ledger_add)
    p = ls.add_parser("show", parents=[common])
    p.set_defaults(func=cmd_ledger_show)


def _add_chart_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("chart", parents=[common],
                       help="self-contained offender chart with live re-scoring")
    p.add_argument("--session", required=True)
    p.add_argument("--driver", default=None, help="one driver, or omit for all")
    p.set_defaults(func=cmd_chart)


def _add_isa_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p_isa = sub.add_parser("isa", parents=[common],
                           help="disassemble shaders and count instruction classes")
    isa_sub = p_isa.add_subparsers(dest="isa_action", required=True)

    p = isa_sub.add_parser("extract", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", required=True, choices=["system", "stock", "custom"])
    p.add_argument("--hash", action="append", default=None, help="explicit hash (repeatable)")
    p.add_argument("--top", type=int, default=25, help="or: top N by offender score")
    p.set_defaults(func=cmd_isa_extract)

    p = isa_sub.add_parser("metrics", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--driver", required=True)
    p.set_defaults(func=cmd_isa_metrics)

    p = isa_sub.add_parser("diff", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.set_defaults(func=cmd_isa_diff)


def _add_compare_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("compare", parents=[common], help="diff two stats tables (Metric 1)")
    p.add_argument("--session", default=None)
    p.add_argument("--a", required=True, help="driver label or path to stats CSV")
    p.add_argument("--b", required=True, help="driver label or path to stats CSV")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_compare)


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
    _add_corpus_parser(sub, common)
    _add_arm_launch_parsers(sub, common)
    _add_bench_parser(sub, common)
    _add_ledger_parser(sub, common)
    _add_chart_parser(sub, common)
    _add_isa_parser(sub, common)
    _add_compare_parser(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except TccError as exc:
        # One base class, caught once. The explicit tuple this replaced was
        # edited from a distance and went stale twice -- CompareError and
        # CollectError both reached users as tracebacks.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

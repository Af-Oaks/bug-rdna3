"""Metric 3: run real game shaders as a deterministic GPU workload.

What SB-0 established, 2026-08-03, on this machine
--------------------------------------------------
The spike answered the question it existed to answer, and the answer is a
scope limit rather than a green light:

    Remnant II (vkd3d-proton, DX12)   0 of 8 compute shaders ran.
                                      All 8 died with a GPUVM fault, e.g.
                                      `radv: GPUVM fault at 0x800044800000,
                                      CLIENT_ID SQC (data), PERMISSION_FAULTS 3`.
    mechabellum (native Vulkan)       4 of 6 ran, cv 0.098%-0.263%.

So the arena + pointer-fill mitigation is **not sufficient for vkd3d-translated
titles**. Those shaders read raw 64-bit pointers out of constant buffers, and
they read their *offsets* from the same buffers -- so filling every 8-byte word
with the arena address makes the pointer valid and the offset enormous, and
`base + huge` lands outside the allocation. You cannot satisfy both with one
pattern, because nothing distinguishes a pointer word from an index word.

Native-Vulkan titles do not have that problem: they use ordinary descriptors,
and the dummy resources bind cleanly.

**Therefore Metric 3 covers native-Vulkan titles. DX12 titles are out of scope
for it and remain covered by Metric 1 (static) and Metric 2 (frame rate).**
That is a real result, not a workaround: it is worth stating in the thesis that
translated D3D12 shaders cannot be isolated from their descriptor heaps.

Why this module runs one process per batch
------------------------------------------
A GPUVM fault destroys the Vulkan device. Every pipeline after it in the same
process is lost. So work is split into batches, each batch is a separate
process under `core.gpuguard`, and a batch that faults costs only its own
pipelines -- the rest of the corpus still gets measured, and the fault is
recorded as a result rather than swallowed.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core import config, gpuguard, paths, util
from core.errors import TccError
from core.session import Session

HARNESS = "shaderlab/harness/tcc-shaderbench"


class ShaderbenchError(TccError):
    pass


@dataclass
class BenchOptions:
    warmup: int = 50
    iterations: int = 200
    repetitions: int = 4
    trim_worst: int = 1
    invocations: int = 1 << 20
    arena_mb: int = 256
    batch: int = 25          # pipelines per process; a fault costs one batch
    timeout_s: float = 300.0


@dataclass
class DriverRun:
    driver: str
    pipelines: list[dict] = field(default_factory=list)
    batches_faulted: int = 0
    batches_total: int = 0
    device: str = ""
    driver_info: str = ""


def harness_path() -> Path:
    p = paths.repo_root() / HARNESS
    if not p.is_file():
        raise ShaderbenchError(
            f"harness not built: {p}. Run `shaderlab/harness/build.sh` first.")
    return p


def _hash_list(foz: Path, tag: int = 7) -> list[str]:
    from shader_extractor.foz import list_hashes

    return sorted(list_hashes(foz, tag))


def _run_batch(session: Session, foz: Path, hashes: list[str], driver: str,
               opts: BenchOptions, tag: str) -> tuple[list[dict], gpuguard.GpuRunResult]:
    """One process, one batch. Returns (pipeline results, guard result)."""
    work_dir = util.ensure_dir(session.subdir("bench") / "shaderbench")
    hash_file = work_dir / f"hashes.{tag}.txt"
    hash_file.write_text("\n".join(hashes) + "\n", encoding="utf-8")
    out_json = work_dir / f"run.{tag}.json"

    profile = config.load_profile_config({"system": "baseline"}.get(driver, driver))
    env = config.profile_env(profile, session.root, force_nocache=True)

    argv = [
        str(harness_path()), "--foz", str(foz), "--hashes", str(hash_file),
        "--out", str(out_json),
        "--warmup", str(opts.warmup), "--iterations", str(opts.iterations),
        "--repetitions", str(opts.repetitions), "--trim-worst", str(opts.trim_worst),
        "--invocations", str(opts.invocations), "--arena-mb", str(opts.arena_mb),
    ]
    result = gpuguard.run_guarded(argv, log_dir=session.subdir("logs"),
                                  step=f"shaderbench_{driver}_{tag}",
                                  env=env, timeout_s=opts.timeout_s)

    rows: list[dict] = []
    if out_json.is_file():
        try:
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            rows = payload.get("pipelines", [])
        except json.JSONDecodeError:
            rows = []   # the process died mid-write; the batch is simply lost

    faulted = _faulted(result, session, driver, tag)
    if faulted:
        # Every pipeline in a faulted batch is suspect: the device died at some
        # point inside it and we cannot tell which one did it without bisecting.
        for r in rows:
            r["status"] = "batch_faulted"

    # A pipeline must NEVER vanish. The process can die for reasons that are not
    # GPU faults at all -- RADV aborts on a SPIR-V capability it does not
    # implement (observed: SpvCapabilityRawAccessChainsNV), which takes the whole
    # batch with it and would otherwise leave those hashes absent from coverage,
    # silently shrinking the denominator.
    reason = ("faulted" if faulted else
              "batch_died" if result.status != "ok" or not rows else "missing")
    seen = {r.get("hash") for r in rows}
    for h in hashes:
        if h not in seen:
            rows.append({"hash": h, "status": reason, "reps_ns": [], "discarded_ns": [],
                         "mean_ns": 0, "cv_pct": 0, "stable": False,
                         "batch": tag, "guard_status": result.status})
    return rows, result


def _faulted(result: gpuguard.GpuRunResult, session: Session, driver: str, tag: str) -> bool:
    """RADV prints the GPUVM fault to stderr even when dmesg is unreadable, so
    the log is the more reliable signal of the two."""
    if result.status == "gpu_reset":
        return True
    log = session.subdir("logs") / f"shaderbench_{driver}_{tag}.stderr.log"
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")
        return "GPUVM fault" in text or "context is lost" in text
    return False


def _run_batch_isolating(session: Session, foz: Path, hashes: list[str], driver: str,
                         opts: BenchOptions, tag: str) -> tuple[list[dict], gpuguard.GpuRunResult]:
    """Run a batch; if the process dies, re-run its pipelines one per process.

    One shader that aborts the driver would otherwise cost the whole batch. The
    retry costs process startup per pipeline and is only paid on failure."""
    rows, guard = _run_batch(session, foz, hashes, driver, opts, tag)
    lost = [r["hash"] for r in rows if r.get("status") in ("batch_died", "batch_faulted", "faulted")]
    if not lost or len(hashes) == 1:
        return rows, guard

    print(f"  [{driver}] batch {tag} lost {len(lost)} pipeline(s); isolating")
    kept = [r for r in rows if r.get("status") not in ("batch_died", "batch_faulted", "faulted")]
    for i, h in enumerate(lost):
        one, _ = _run_batch(session, foz, [h], driver, opts, f"{tag}i{i:03d}")
        kept.extend(one)
    return kept, guard


def run_driver(session: Session, foz: Path, driver: str, hashes: list[str],
               opts: BenchOptions) -> DriverRun:
    out = DriverRun(driver=driver)
    batches = [hashes[i:i + opts.batch] for i in range(0, len(hashes), opts.batch)]
    out.batches_total = len(batches)
    for i, batch in enumerate(batches):
        rows, guard = _run_batch_isolating(session, foz, batch, driver, opts, f"{i:04d}")
        if _faulted(guard, session, driver, f"{i:04d}"):
            out.batches_faulted += 1
        out.pipelines.extend(rows)
        print(f"  [{driver}] batch {i + 1}/{len(batches)}: "
              f"{sum(1 for r in rows if r.get('status') == 'ok')} ok, {guard.status}")
    return out


def run(session: Session, game: str, drivers: list[str], opts: BenchOptions | None = None,
        top: int | None = None) -> Path:
    """Benchmark a game's compute corpus under each driver, interleaved by batch.

    Drivers alternate at batch granularity (A B A B ...) rather than running one
    driver to completion then the other. GPU nanoseconds drift with clock and
    temperature over minutes, and that drift is larger than the compiler effect
    being measured -- alternating makes it hit both sides equally so it cancels
    in the delta. A delta is only ever claimed within one invocation of this
    function.
    """
    from shader_extractor import corpus as corpus_mod

    opts = opts or BenchOptions()
    foz = corpus_mod.corpus_foz(game)
    if not foz.is_file():
        raise ShaderbenchError(
            f"no corpus for {game!r}: run `tcc corpus build --game {game}` first")

    hashes = _hash_list(foz, tag=7)
    if not hashes:
        raise ShaderbenchError(
            f"{game}: no compute pipelines in the corpus. Stage 1 is compute-only; "
            "a graphics-heavy title legitimately yields none.")
    if top:
        hashes = hashes[:top]

    runs = {d: DriverRun(driver=d) for d in drivers}
    batches = [hashes[i:i + opts.batch] for i in range(0, len(hashes), opts.batch)]
    for d in drivers:
        runs[d].batches_total = len(batches)

    for i, batch in enumerate(batches):
        for d in drivers:   # ABAB… interleave at batch granularity
            tag = f"{i:04d}"
            rows, guard = _run_batch_isolating(session, foz, batch, d, opts, tag)
            if _faulted(guard, session, d, tag):
                runs[d].batches_faulted += 1
            runs[d].pipelines.extend(rows)
        ok = {d: sum(1 for r in runs[d].pipelines if r.get("status") == "ok") for d in drivers}
        print(f"  batch {i + 1}/{len(batches)}  cumulative ok: " +
              " ".join(f"{d}={ok[d]}" for d in drivers))

    payload = {
        "session_id": session.session_id,
        "game": game,
        "corpus": str(foz),
        "pipelines_requested": len(hashes),
        "options": vars(opts),
        "drivers": {d: {
            "batches_total": runs[d].batches_total,
            "batches_faulted": runs[d].batches_faulted,
            "coverage": _coverage(runs[d].pipelines),
            "pipelines": runs[d].pipelines,
        } for d in drivers},
        "deltas": _deltas(runs, drivers),
        "caveat": (
            "Synthetic inputs: absolute nanoseconds are not the game's nanoseconds. "
            "Only the within-run relative delta between drivers is meaningful. "
            "vkd3d-translated titles are out of scope -- their shaders read raw "
            "pointers out of descriptor heaps and fault when isolated (SB-0)."),
    }
    out = session.subdir("bench") / f"shaderbench.{game}.json"
    util.write_json(out, payload)
    session.record_artifact(out, kind="shaderbench_run", producer="tcc bench shaders",
                            confidence="exact")
    return out


def _coverage(rows: list[dict]) -> dict:
    c: dict[str, int] = {}
    for r in rows:
        c[r.get("status", "unknown")] = c.get(r.get("status", "unknown"), 0) + 1
    return c


def _deltas(runs: dict[str, DriverRun], drivers: list[str]) -> list[dict]:
    """Per-shader delta between the first two drivers, stable rows only.

    An unstable measurement is excluded from the delta rather than averaged in:
    a shader whose own repetitions disagree by more than the gate cannot support
    a claim about a 2% compiler effect."""
    if len(drivers) < 2:
        return []
    a, b = drivers[0], drivers[1]
    idx = {}
    for r in runs[a].pipelines:
        if r.get("status") == "ok" and r.get("stable"):
            idx[r["hash"]] = r
    out = []
    for r in runs[b].pipelines:
        if r.get("status") != "ok" or not r.get("stable"):
            continue
        base = idx.get(r["hash"])
        if not base or not base.get("mean_ns"):
            continue
        out.append({
            "hash": r["hash"],
            f"{a}_ns": base["mean_ns"],
            f"{b}_ns": r["mean_ns"],
            "delta_ns": r["mean_ns"] - base["mean_ns"],
            "delta_pct": round(100.0 * (r["mean_ns"] - base["mean_ns"]) / base["mean_ns"], 4),
        })
    out.sort(key=lambda d: d["delta_pct"])
    return out

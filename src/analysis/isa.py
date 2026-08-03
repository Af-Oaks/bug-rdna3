"""Parse the RDNA3 machine code ACO actually emitted, and diff it A vs B.

Metric 1 so far is the driver's *self-report* — VGPR counts, VOPD counts, ACO's
own latency model. This module reads the instructions themselves.

`fossilize-disasm --target isa` writes one file per shader stage containing
three concatenated sections:

    Representation: NIR Shader(s)
    Representation: ACO IR
    Representation: Assembly (Final Assembly)     <- the only one parsed here

Only the last is real gfx1101 machine code. NIR and ACO IR are compiler
intermediates; counting mnemonics in them would measure the wrong thing.

Why this exists
---------------
The RDNA3 hypothesis is about instructions the compiler was *forced to insert*.
RDNA3 removed the hardware interlocks that RDNA2 used for VALU data hazards, so
ACO must emit `s_delay_alu` to tell the hardware how long to wait. That
instruction is pure overhead — it computes nothing — and its density is the
closest static proxy the thesis has for hazard-handling cost.

The honest limit, which must travel with every number this module produces:
**a count is not a cost.** An `s_delay_alu` added on a path where the wave was
already stalled on memory costs nothing. Static instruction deltas say what
changed in the code; only shaderbench (Metric 3) or SQTT can say what it cost.
Nothing here should ever be reported as a performance result on its own.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from core import util
from core.errors import TccError
from core.session import Session

_FINAL_ASSEMBLY = "Final Assembly"
_SECTION_RE = re.compile(r"^Representation:\s*(.+?)\s*$", re.M)

# A disassembly line looks like:
#   v_dual_fmac_f32 v1, v2, v3 :: v_dual_mov_b32 v4, v5   ; encoding
#   s_delay_alu instid0(VALU_DEP_1)                       ; 0xbf870001
# Leading offsets/labels vary between builds, so anchor on the mnemonic: the
# first token that starts with a known instruction prefix.
_MNEMONIC_RE = re.compile(r"^\s*(?:[0-9a-fA-F]{4,}:\s*)?([svb][a-z0-9_]+)\b")

#: Instruction classes. Order matters: the first match wins, so the specific
#: dual-issue and hazard prefixes are tested before the generic v_/s_ buckets.
_CLASSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("vopd",        re.compile(r"^v_dual_")),
    ("s_delay_alu", re.compile(r"^s_delay_alu")),
    ("s_waitcnt",   re.compile(r"^s_wait")),
    ("s_nop",       re.compile(r"^s_nop")),
    ("branch",      re.compile(r"^s_(branch|cbranch|setpc|swappc|call)")),
    ("export",      re.compile(r"^exp\b|^s_sendmsg")),
    ("vmem",        re.compile(r"^(buffer_|image_|global_|scratch_|flat_|tbuffer_)")),
    ("smem",        re.compile(r"^s_(load|store|buffer_load|buffer_store)")),
    ("lds",         re.compile(r"^ds_")),
    ("valu",        re.compile(r"^v_")),
    ("salu",        re.compile(r"^s_")),
)

#: Instructions that exist only to make the hardware wait. RDNA3 moved VALU
#: hazard handling from hardware interlocks into these, so their share of the
#: instruction stream is the hypothesis-1 signal.
STALL_CLASSES = ("s_delay_alu", "s_waitcnt", "s_nop")


class IsaError(TccError):
    pass


@dataclass
class ShaderIsa:
    path: Path
    pipeline_hash: str
    stage: str
    total_instructions: int
    counts: dict[str, int] = field(default_factory=dict)
    #: s_delay_alu operands, e.g. "VALU_DEP_1" -> how many. RDNA3 encodes the
    #: required wait distance in the operand, so the distribution says whether
    #: ACO is inserting cheap 1-cycle waits or expensive long ones.
    delay_kinds: dict[str, int] = field(default_factory=dict)

    @property
    def stall_ratio(self) -> float:
        if not self.total_instructions:
            return 0.0
        return sum(self.counts.get(c, 0) for c in STALL_CLASSES) / self.total_instructions

    @property
    def vopd_ratio(self) -> float:
        """Dual-issue instructions per VALU instruction. Not per *total*: VOPD
        replaces VALU work, so VALU is the population that could have paired."""
        valu = self.counts.get("valu", 0) + self.counts.get("vopd", 0)
        return self.counts.get("vopd", 0) / valu if valu else 0.0

    def to_row(self) -> dict:
        row = {
            "pipeline_hash": self.pipeline_hash,
            "stage": self.stage,
            "total_instructions": self.total_instructions,
            "stall_ratio": round(self.stall_ratio, 6),
            "vopd_ratio": round(self.vopd_ratio, 6),
        }
        row.update({f"n_{k}": v for k, v in sorted(self.counts.items())})
        return row


def final_assembly(text: str) -> str:
    """The Final Assembly section only. Raises rather than guessing: silently
    counting mnemonics from the NIR or ACO IR section would produce numbers
    that look plausible and mean nothing."""
    marks = [(m.start(), m.group(1)) for m in _SECTION_RE.finditer(text)]
    for i, (pos, name) in enumerate(marks):
        if _FINAL_ASSEMBLY.lower() in name.lower():
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            return text[pos:end]
    raise IsaError(
        f"no {_FINAL_ASSEMBLY!r} section found; sections present: "
        f"{[n for _, n in marks] or 'none'}. Was this produced with "
        "`fossilize-disasm --target isa`?"
    )


def classify(mnemonic: str) -> str | None:
    for name, pattern in _CLASSES:
        if pattern.match(mnemonic):
            return name
    return None


def parse_text(text: str, pipeline_hash: str = "", stage: str = "",
               path: Path | None = None) -> ShaderIsa:
    body = final_assembly(text)
    counts: Counter[str] = Counter()
    delays: Counter[str] = Counter()
    total = 0

    for line in body.splitlines():
        line = line.split(";")[0]  # strip the hex encoding comment
        if not line.strip() or line.lstrip().startswith("Representation"):
            continue
        # A dual-issue line encodes two operations separated by "::"; both are
        # real instructions and both are counted, but the line is one VOPD.
        m = _MNEMONIC_RE.match(line)
        if not m:
            continue
        mnemonic = m.group(1)
        cls = classify(mnemonic)
        if cls is None:
            continue
        total += 1
        counts[cls] += 1
        if cls == "s_delay_alu":
            for kind in re.findall(r"instid\d+\(([A-Z0-9_]+)\)", line):
                delays[kind] += 1

    return ShaderIsa(
        path=path or Path("<memory>"),
        pipeline_hash=pipeline_hash,
        stage=stage,
        total_instructions=total,
        counts=dict(counts),
        delay_kinds=dict(delays),
    )


def parse_file(path: Path) -> ShaderIsa:
    """Filenames from fossilize-disasm are
    <module_hash>.<entry_point>.<pipeline_hash>.<stage_ext>."""
    path = Path(path)
    parts = path.name.split(".")
    pipeline_hash = parts[2] if len(parts) >= 4 else ""
    stage = parts[-1] if len(parts) >= 4 else ""
    return parse_text(path.read_text(encoding="utf-8", errors="replace"),
                      pipeline_hash=pipeline_hash, stage=stage, path=path)


def parse_dir(isa_dir: Path) -> list[ShaderIsa]:
    isa_dir = Path(isa_dir)
    if not isa_dir.is_dir():
        raise IsaError(
            f"no ISA dump at {isa_dir}; run `tcc isa extract --driver {isa_dir.name}` first")
    out: list[ShaderIsa] = []
    for path in sorted(isa_dir.iterdir()):
        if path.is_file():
            try:
                out.append(parse_file(path))
            except IsaError:
                continue  # not a --target isa dump; skip rather than abort
    return out


# ---------------------------------------------------------------------------
# extract: disassemble the ranked offenders
# ---------------------------------------------------------------------------


def extract(session: Session, driver: str, hashes: list[str],
            foz_path: Path | None = None) -> Path:
    """Disassemble each hash into <session>/isa/<driver>/ and write metrics."""
    from core import config
    from shader_extractor import foz as foz_mod

    source = foz_mod.resolve_foz(session, explicit=foz_path)
    out_dir = util.ensure_dir(session.subdir("isa") / driver)

    profile = config.load_profile_config({"system": "baseline"}.get(driver, driver))
    env = config.profile_env(profile, session.root, force_nocache=True)

    buckets = foz_mod.classify_hashes(source, hashes)
    kind_of = {h: name for name, group in buckets.items() for h in group}
    missing = [h for h in hashes if h not in kind_of]
    if missing:
        raise IsaError(f"not present in {source.name} as graphics/compute/raytracing: {missing[:5]}")

    written = 0
    for h in hashes:
        foz_mod.disasm(session, source, h, kind_of[h], out_dir, env, target="isa")
        written += 1

    rows = [s.to_row() for s in parse_dir(out_dir)]
    out_csv = session.subdir("isa") / f"isa_metrics.{driver}.csv"
    _write_csv(out_csv, rows)
    session.record_artifact(out_csv, kind="isa_metrics", producer="tcc isa extract", confidence="exact")
    return out_csv


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    if not rows:
        raise IsaError("no shaders parsed; nothing to write")
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    util.ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# diff: the same shader under two compilers
# ---------------------------------------------------------------------------


def diff(a: ShaderIsa, b: ShaderIsa) -> dict:
    classes = sorted(set(a.counts) | set(b.counts))
    return {
        "pipeline_hash": a.pipeline_hash or b.pipeline_hash,
        "stage": a.stage or b.stage,
        "total_instructions": {"a": a.total_instructions, "b": b.total_instructions,
                               "delta": b.total_instructions - a.total_instructions},
        "stall_ratio": {"a": round(a.stall_ratio, 6), "b": round(b.stall_ratio, 6),
                        "delta": round(b.stall_ratio - a.stall_ratio, 6)},
        "vopd_ratio": {"a": round(a.vopd_ratio, 6), "b": round(b.vopd_ratio, 6),
                       "delta": round(b.vopd_ratio - a.vopd_ratio, 6)},
        "classes": {c: {"a": a.counts.get(c, 0), "b": b.counts.get(c, 0),
                        "delta": b.counts.get(c, 0) - a.counts.get(c, 0)}
                    for c in classes},
        "delay_kinds": {k: {"a": a.delay_kinds.get(k, 0), "b": b.delay_kinds.get(k, 0),
                            "delta": b.delay_kinds.get(k, 0) - a.delay_kinds.get(k, 0)}
                        for k in sorted(set(a.delay_kinds) | set(b.delay_kinds))},
    }


def diff_dirs(session: Session, driver_a: str, driver_b: str) -> Path:
    """Diff every shader disassembled under both drivers, join on pipeline hash."""
    dir_a = session.subdir("isa") / driver_a
    dir_b = session.subdir("isa") / driver_b
    for d, label in ((dir_a, driver_a), (dir_b, driver_b)):
        if not d.is_dir():
            raise IsaError(f"no ISA dump for {label!r}; run `tcc isa extract --driver {label}` first")

    index_a = {(s.pipeline_hash, s.stage): s for s in parse_dir(dir_a)}
    index_b = {(s.pipeline_hash, s.stage): s for s in parse_dir(dir_b)}
    shared = sorted(set(index_a) & set(index_b))
    if not shared:
        raise IsaError("no shader disassembled under both drivers")

    diffs = [diff(index_a[k], index_b[k]) for k in shared]
    changed = [d for d in diffs if d["total_instructions"]["delta"]
               or d["classes"].get("s_delay_alu", {}).get("delta")
               or d["classes"].get("vopd", {}).get("delta")]

    payload = {
        "a": driver_a, "b": driver_b,
        "shaders_compared": len(shared),
        "shaders_changed": len(changed),
        "only_in_a": len(set(index_a) - set(index_b)),
        "only_in_b": len(set(index_b) - set(index_a)),
        "caveat": ("Instruction counts are static. A count is not a cost -- an "
                   "s_delay_alu on a path already stalled on memory costs nothing. "
                   "Use shaderbench or SQTT before claiming a performance effect."),
        "diffs": diffs,
    }
    out = session.subdir("isa") / f"isa_diff.{driver_a}_vs_{driver_b}.json"
    util.write_json(out, payload)
    session.record_artifact(out, kind="isa_diff", producer="tcc isa diff", confidence="exact")
    return out


def summarize(rows: list[ShaderIsa]) -> dict:
    """Corpus-level aggregate. Ratios are averaged per shader, not pooled over
    all instructions: a 7,000-instruction shader must not outvote 200 small
    ones when the question is "how often does ACO insert waits"."""
    if not rows:
        return {"shaders": 0}
    totals: Counter[str] = Counter()
    for r in rows:
        totals.update(r.counts)
    n = len(rows)
    return {
        "shaders": n,
        "instructions_total": sum(r.total_instructions for r in rows),
        "stall_ratio_mean": round(sum(r.stall_ratio for r in rows) / n, 6),
        "vopd_ratio_mean": round(sum(r.vopd_ratio for r in rows) / n, 6),
        "shaders_with_vopd": sum(1 for r in rows if r.counts.get("vopd")),
        "class_totals": dict(sorted(totals.items())),
    }

"""Run GPU work without losing the machine when a compiler change goes wrong.

Aggressive ACO changes do not crash cleanly. They produce shaders that fault on
a bad address or loop forever, which hangs the GPU queue -- and a hung queue can
take the desktop with it. `SHADERBENCH_PLAN` §2.1 is explicit about the
mechanism: vkd3d-proton lowers D3D12 descriptor heaps into raw 64-bit pointers
with no bounds checking, so a synthesized pointer that is wrong by one is a page
fault rather than an exception.

Three rules follow, and this module exists to enforce them:

1. **Never run untrusted GPU work in the session manager's process.** A queue
   loss kills the process holding the device; if that process is also holding
   the session, the run's records die with it. Everything here goes through a
   subprocess with a hard timeout.

2. **A GPU reset is a RESULT, not a failure to hide.** A compiler change that
   hangs the GPU is a finding worth writing down. `GpuRunResult.status`
   distinguishes ok / timeout / gpu_reset / crashed, and none of them collapse
   to a bool.

3. **Leave evidence before you risk the hang, not after.** The kernel ring
   timeout is recorded in dmesg, which is readable after the fact, but the
   shader that caused it is only knowable if it was written down first.

Detection is best-effort by construction: reading `dmesg` needs permission this
process may not have, and the reset may land after the child is already dead.
`gpu_reset_detected` is therefore three-valued -- True / False / None for
"could not tell" -- and never silently reports False when it simply could not
look.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import TccError

#: amdgpu ring timeouts, resets and VM faults, as they appear in dmesg.
_RESET_PATTERNS = (
    re.compile(r"amdgpu.*ring .* timeout", re.I),
    re.compile(r"amdgpu.*GPU reset", re.I),
    re.compile(r"amdgpu.*VM_L2_PROTECTION_FAULT", re.I),
    re.compile(r"amdgpu.*soft reset", re.I),
    re.compile(r"drm.*GPU hang", re.I),
    re.compile(r"\[drm\].*reset", re.I),
)


class GpuGuardError(TccError):
    """Raised when the guard cannot run the work at all."""


@dataclass
class GpuRunResult:
    status: str  # ok | timeout | gpu_reset | crashed
    returncode: int | None
    duration_s: float
    stdout_log: Path | None
    stderr_log: Path | None
    gpu_reset_detected: bool | None  # None = could not check
    dmesg_excerpt: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _dmesg_lines() -> list[str] | None:
    """Recent kernel log, or None if we are not allowed to read it.

    `dmesg` is restricted by `kernel.dmesg_restrict` on most distributions, so
    "no reset found" and "not allowed to look" must not be the same answer."""
    if not shutil.which("dmesg"):
        return None
    try:
        proc = subprocess.run(["dmesg", "--ctime", "--level=err,warn,crit"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def scan_for_reset(since_index: int = 0) -> tuple[bool | None, list[str]]:
    """(reset_detected, matching lines). `since_index` is a line count captured
    before the risky work, so only new kernel messages are considered."""
    lines = _dmesg_lines()
    if lines is None:
        return None, []
    fresh = lines[since_index:]
    hits = [ln for ln in fresh if any(p.search(ln) for p in _RESET_PATTERNS)]
    return bool(hits), hits[-20:]


def dmesg_mark() -> int:
    """Line count to pass back to scan_for_reset(). 0 when dmesg is unreadable,
    which makes the later scan consider everything -- noisier, never wrong."""
    lines = _dmesg_lines()
    return len(lines) if lines else 0


def run_guarded(
    argv: list[str],
    log_dir: Path,
    step: str,
    env: dict[str, str] | None = None,
    timeout_s: float = 120.0,
) -> GpuRunResult:
    """Run GPU work in its own process, bounded, with reset detection.

    The child is killed on timeout and its output is on disk either way -- a
    hang must still leave behind what it was doing. Nothing here raises for a
    GPU fault: faults are recorded and returned, because a compiler that hangs
    the GPU is data.
    """
    import os

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = step.replace("/", "_").replace(" ", "_")
    stdout_path = log_dir / f"{safe}.stdout.log"
    stderr_path = log_dir / f"{safe}.stderr.log"

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    mark = dmesg_mark()
    started = time.monotonic()
    status = "ok"
    returncode: int | None = None

    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            proc = subprocess.Popen([str(a) for a in argv], env=run_env,
                                    stdout=out, stderr=err, start_new_session=True)
        except OSError as exc:
            raise GpuGuardError(f"could not start {argv[0]!r}: {exc}") from exc
        try:
            returncode = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # SIGKILL, not SIGTERM: a process wedged on a lost queue is in an
            # uninterruptible wait and will not handle a signal it can catch.
            proc.kill()
            try:
                returncode = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                returncode = None
            status = "timeout"

    duration_s = round(time.monotonic() - started, 3)

    # A reset can land in the log slightly after the child dies.
    time.sleep(0.5)
    reset, excerpt = scan_for_reset(mark)
    if reset:
        status = "gpu_reset"
    elif status == "ok" and returncode not in (0, None):
        status = "crashed"

    return GpuRunResult(
        status=status,
        returncode=returncode,
        duration_s=duration_s,
        stdout_log=stdout_path,
        stderr_log=stderr_path,
        gpu_reset_detected=reset,
        dmesg_excerpt=excerpt,
    )

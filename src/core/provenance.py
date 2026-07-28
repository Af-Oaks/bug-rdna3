"""Provenance helpers: hashing, environment snapshots, recorded subprocess runs."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from . import util

if TYPE_CHECKING:
    from .session import Session

# Prefixes worth snapshotting: Vulkan loader, RADV/Mesa driver, our own state.
ENV_SNAPSHOT_PREFIXES = ("VK_", "RADV_", "MESA_", "ENABLE_VULKAN_", "AMD_", "TCC_")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def env_snapshot(prefixes: tuple[str, ...] = ENV_SNAPSHOT_PREFIXES) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(prefixes)}


def _pump(stream: IO[bytes], log_file: IO[bytes], mirror: IO[bytes]) -> None:
    for line in iter(stream.readline, b""):
        log_file.write(line)
        log_file.flush()
        try:
            mirror.write(line)
            mirror.flush()
        except (OSError, ValueError):
            pass  # mirror stream closed (e.g. captured test output); logging still happened
    stream.close()


def run_recorded(
    session: "Session",
    step: str,
    argv: list[str],
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run argv, tee stdout/stderr into session logs/<step>.{stdout,stderr}.log,
    and append a step record (name, argv, timestamp, returncode, duration_s...)
    to session.json via session.record_step."""
    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    log_dir = util.ensure_dir(session.subdir("logs"))
    safe_name = step.replace("/", "_").replace(" ", "_")
    stdout_path = log_dir / f"{safe_name}.stdout.log"
    stderr_path = log_dir / f"{safe_name}.stderr.log"

    argv_str = [str(a) for a in argv]
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("wb") as out_log, stderr_path.open("wb") as err_log:
        proc = subprocess.Popen(
            argv_str, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out_thread = threading.Thread(target=_pump, args=(proc.stdout, out_log, sys.stdout.buffer))
        err_thread = threading.Thread(target=_pump, args=(proc.stderr, err_log, sys.stderr.buffer))
        out_thread.start()
        err_thread.start()
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = proc.wait()
            timed_out = True
        out_thread.join()
        err_thread.join()
    duration_s = round(time.monotonic() - started, 3)

    session.record_step(
        step,
        argv_str,
        returncode,
        duration_s=duration_s,
        timed_out=timed_out,
        stdout_log=str(stdout_path.relative_to(session.root)),
        stderr_log=str(stderr_path.relative_to(session.root)),
        env_snapshot=env_snapshot(),
    )
    return subprocess.CompletedProcess(argv_str, returncode)

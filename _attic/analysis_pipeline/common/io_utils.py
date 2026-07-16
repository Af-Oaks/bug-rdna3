"""I/O, hashing, and formatting helpers for manifests and artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .constants import REPO_ROOT

HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{16,64}\b")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = normalized.strip("_")
    return normalized or "unnamed"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict | list) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def file_metadata(path: Path) -> dict:
    stat = path.stat()
    return {
        "canonical_path": str(path.resolve()),
        "repo_relative_path": repo_relative(path),
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "sha256": sha256_of_file(path),
    }


def unique_destination_path(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    counter = 2
    while True:
        candidate = destination.with_name(f"{stem}__{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def copy_file(source: Path, destination_dir: Path) -> Path:
    ensure_dir(destination_dir)
    destination = unique_destination_path(destination_dir / source.name)
    shutil.copy2(source, destination)
    return destination


def extract_hex_tokens(text: str) -> list[str]:
    return sorted({token.lower() for token in HEX_TOKEN_RE.findall(text)})


def extract_hex_tokens_from_path(path: Path, max_bytes: int = 5 * 1024 * 1024) -> list[str]:
    tokens = extract_hex_tokens(path.name)
    try:
        if path.suffix.lower() in {".json", ".md", ".txt", ".log", ".csv", ".asm", ".isa", ".foz"}:
            content = path.read_text(encoding="utf-8", errors="ignore")
            if len(content.encode("utf-8")) <= max_bytes:
                tokens.extend(extract_hex_tokens(content))
            else:
                tokens.extend(extract_hex_tokens(content[: max_bytes // 2]))
    except OSError:
        pass
    return sorted(set(tokens))


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

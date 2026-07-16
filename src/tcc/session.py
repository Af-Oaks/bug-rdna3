"""Session lifecycle: create, load, list, and record steps/artifacts.

A session lives at data/sessions/<game>/<session_id>/ where
session_id = "<YYYYMMDD-HHMMSS>_<game>_<scene>". session.json is the
manifest (schema_version 2); artifacts.json is the artifact registry.
Both are validated against src/tcc/schemas/*.schema.json on every save().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from . import paths, provenance, util

SCHEMA_VERSION = 2
SESSION_SUBDIRS = ("logs", "foz", "stats", "isa", "isa_metrics", "captures", "bench", "reports")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


class SessionError(Exception):
    """Base class for session lookup/validation errors."""


class SessionNotFoundError(SessionError):
    pass


class SessionAmbiguousError(SessionError):
    pass


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "unnamed"


def _load_schema(name: str) -> dict:
    return util.read_json(_SCHEMA_DIR / name)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _note_entry(text: str) -> dict[str, str]:
    return {"timestamp": _now_iso(), "text": text}


def _all_session_dirs() -> list[Path]:
    root = paths.data_dir() / "sessions"
    if not root.exists():
        return []
    return sorted(p.parent for p in root.glob("*/*/session.json"))


@dataclass
class Session:
    root: Path
    session_id: str
    game: str
    scene: str
    created_at: str
    status: str
    profiles_used: list[str] = field(default_factory=list)
    tool_resolution: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    # -- paths --------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.root / "session.json"

    @property
    def registry_path(self) -> Path:
        return self.root / "artifacts.json"

    def subdir(self, name: str) -> Path:
        return self.root / name

    # -- lifecycle ------------------------------------------------------
    @classmethod
    def create(cls, game: str, scene: str, note: str | None = None) -> "Session":
        game_slug = slugify(game)
        scene_slug = slugify(scene)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{timestamp}_{game_slug}_{scene_slug}"
        root = paths.session_root(game_slug, session_id)
        for name in SESSION_SUBDIRS:
            util.ensure_dir(root / name)

        session = cls(
            root=root,
            session_id=session_id,
            game=game_slug,
            scene=scene_slug,
            created_at=_now_iso(),
            status="open",
        )
        if note:
            session.notes.append(_note_entry(note))
        session.save()
        return session

    @classmethod
    def load(cls, ref: str) -> "Session":
        dirs = _all_session_dirs()
        if ref == "@last":
            if not dirs:
                raise SessionNotFoundError("No sessions exist yet.")
            return cls._load_dir(max(dirs, key=lambda p: p.name))

        exact = [p for p in dirs if p.name == ref]
        if exact:
            return cls._load_dir(exact[0])

        matches = [p for p in dirs if ref in p.name]
        if not matches:
            raise SessionNotFoundError(f"No session matches {ref!r}.")
        if len(matches) > 1:
            names = ", ".join(sorted(p.name for p in matches))
            raise SessionAmbiguousError(f"Ambiguous session ref {ref!r}; matches: {names}")
        return cls._load_dir(matches[0])

    @classmethod
    def _load_dir(cls, root: Path) -> "Session":
        manifest = util.read_json(root / "session.json")
        registry_path = root / "artifacts.json"
        registry = util.read_json(registry_path) if registry_path.exists() else {"artifacts": []}
        return cls(
            root=root,
            session_id=manifest["session_id"],
            game=manifest["game"],
            scene=manifest["scene"],
            created_at=manifest["created_at"],
            status=manifest["status"],
            profiles_used=manifest.get("profiles_used", []),
            tool_resolution=manifest.get("tool_resolution", {}),
            steps=manifest.get("steps", []),
            notes=manifest.get("notes", []),
            artifacts=registry.get("artifacts", []),
        )

    # -- persistence ------------------------------------------------------
    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "game": self.game,
            "scene": self.scene,
            "created_at": self.created_at,
            "status": self.status,
            "profiles_used": self.profiles_used,
            "tool_resolution": self.tool_resolution,
            "steps": self.steps,
            "notes": self.notes,
        }

    def to_registry(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "artifacts": self.artifacts,
        }

    def save(self) -> None:
        manifest = self.to_manifest()
        jsonschema.validate(manifest, _load_schema("session_manifest.schema.json"))
        util.write_json(self.manifest_path, manifest)

        registry = self.to_registry()
        jsonschema.validate(registry, _load_schema("artifact_registry.schema.json"))
        util.write_json(self.registry_path, registry)

    # -- mutation ----------------------------------------------------------
    def record_step(self, name: str, argv: list[str], returncode: int | None, **extra: Any) -> None:
        step = {
            "name": name,
            "argv": [str(a) for a in argv],
            "timestamp": _now_iso(),
            "returncode": returncode,
        }
        step.update(extra)
        self.steps.append(step)
        self.save()

    def record_artifact(
        self, path: Path, kind: str, producer: str = "", confidence: str = "exact"
    ) -> dict[str, Any]:
        path = Path(path)
        entry = {
            "path": str(path.resolve()),
            "sha256": provenance.sha256_file(path),
            "kind": kind,
            "producer": producer,
            "timestamp": _now_iso(),
            "confidence": confidence,
            "size_bytes": path.stat().st_size,
        }
        self.artifacts = [a for a in self.artifacts if a["path"] != entry["path"]]
        self.artifacts.append(entry)
        self.save()
        return entry

    def add_note(self, text: str) -> None:
        self.notes.append(_note_entry(text))
        self.save()

    def use_profile(self, profile_name: str) -> None:
        if profile_name not in self.profiles_used:
            self.profiles_used.append(profile_name)
            self.save()

    def close(self) -> None:
        self.status = "closed"
        self.save()


def list_sessions(game: str | None = None) -> list[dict[str, Any]]:
    game_slug = slugify(game) if game else None
    summaries = []
    for d in _all_session_dirs():
        if game_slug and d.parent.name != game_slug:
            continue
        manifest = util.read_json(d / "session.json")
        summaries.append(
            {
                "session_id": manifest["session_id"],
                "game": manifest["game"],
                "scene": manifest["scene"],
                "status": manifest["status"],
                "created_at": manifest["created_at"],
            }
        )
    return sorted(summaries, key=lambda s: s["session_id"])

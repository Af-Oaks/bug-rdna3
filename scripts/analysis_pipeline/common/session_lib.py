"""Session creation, manifest management, and artifact registration."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    ANALYSIS_ROOT,
    GAMES_ROOT,
    MANIFEST_VERSION,
    SCHEMA_VERSION,
    SESSION_DIR_NAMES,
    TRACK_MANIFEST_FILENAMES,
    TRACK_STATUS_KEYS,
)
from .io_utils import (
    copy_file,
    ensure_dir,
    file_metadata,
    local_timestamp,
    now_utc_iso,
    read_json,
    repo_relative,
    slugify,
    write_json,
    write_text,
)
from .validation import require_file, require_keys


def game_root(game_slug: str) -> Path:
    return GAMES_ROOT / slugify(game_slug)


def game_config_path(game_slug: str) -> Path:
    return game_root(game_slug) / "config" / "game_config.json"


def build_session_id(game_slug: str, scene_slug: str, timestamp: str | None = None) -> str:
    session_timestamp = timestamp or local_timestamp()
    return f"{slugify(game_slug)}__{slugify(scene_slug)}__{session_timestamp}"


def session_root(game_slug: str, session_id: str) -> Path:
    return game_root(game_slug) / "sessions" / session_id


def session_paths(root: Path) -> dict[str, Path]:
    track_a_root = root / SESSION_DIR_NAMES["track_a"]
    track_b_root = root / SESSION_DIR_NAMES["track_b"]
    track_c_root = root / SESSION_DIR_NAMES["track_c"]
    manifests_root = root / SESSION_DIR_NAMES["manifests"]
    metadata_root = root / SESSION_DIR_NAMES["metadata"]
    notes_root = root / SESSION_DIR_NAMES["notes"]
    exports_root = root / SESSION_DIR_NAMES["exports"]
    return {
        "root": root,
        "manifests_dir": manifests_root,
        "metadata_dir": metadata_root,
        "notes_dir": notes_root,
        "exports_dir": exports_root,
        "track_a_root": track_a_root,
        "track_a_renderdoc_dir": track_a_root / "renderdoc",
        "track_a_screenshots_dir": track_a_root / "screenshots",
        "track_a_frame_markers_dir": track_a_root / "frame_markers",
        "track_a_logs_dir": track_a_root / "logs",
        "track_b_root": track_b_root,
        "track_b_inputs_dir": track_b_root / "inputs" / "foz",
        "track_b_extracted_dir": track_b_root / "extracted",
        "track_b_spirv_dir": track_b_root / "extracted" / "spirv",
        "track_b_isa_dir": track_b_root / "extracted" / "isa",
        "track_b_disassembly_dir": track_b_root / "extracted" / "disassembly",
        "track_b_summaries_dir": track_b_root / "summaries",
        "track_c_root": track_c_root,
        "track_c_inputs_dir": track_c_root / "inputs",
        "track_c_isa_dir": track_c_root / "inputs" / "isa_dumps",
        "track_c_compiler_logs_dir": track_c_root / "inputs" / "compiler_logs",
        "track_c_rga_dir": track_c_root / "inputs" / "rga_reports",
        "track_c_profiling_dir": track_c_root / "inputs" / "profiling",
        "track_c_annotations_dir": track_c_root / "inputs" / "manual_annotations",
        "track_c_outputs_dir": track_c_root / "outputs",
        "session_manifest": manifests_root / "session_manifest.json",
        "artifact_registry": manifests_root / "artifact_registry.json",
        "track_a_manifest": manifests_root / TRACK_MANIFEST_FILENAMES["track_a"],
        "track_b_manifest": manifests_root / TRACK_MANIFEST_FILENAMES["track_b"],
        "track_c_manifest": manifests_root / TRACK_MANIFEST_FILENAMES["track_c"],
        "capture_environment": metadata_root / "capture_environment.json",
        "tool_resolution": metadata_root / "tool_resolution.json",
        "operator_notes": notes_root / "operator_notes.md",
        "scene_description": notes_root / "scene_description.md",
        "hypotheses": notes_root / "hypotheses.md",
        "session_export": exports_root / "thesis_session_summary.md",
        "track_a_instructions": track_a_root / "capture_instructions.md",
        "manual_annotation_template": track_c_root / "manual_annotation.json",
    }


def default_track_manifest(session_id: str, track_key: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "session_id": session_id,
        "track": track_key,
        "status": "not_started",
        "registered_artifacts": [],
        "generated_outputs": [],
        "commands": [],
        "notes": [],
    }


def default_artifact_registry(session_id: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "session_id": session_id,
        "updated_at": now_utc_iso(),
        "artifacts": [],
    }


def default_tool_resolution() -> dict:
    return {"updated_at": now_utc_iso(), "tools": {}}


def load_game_config(game_slug: str) -> dict:
    path = game_config_path(game_slug)
    require_file(path, "Game config")
    payload = read_json(path)
    require_keys(payload, ["game_slug", "display_name"], "Game config")
    return payload


def initialize_session(
    *,
    game_slug: str,
    scene_slug: str,
    settings_profile: str,
    operator_notes: str,
    comparison_cohort: str,
    proton_version: str | None,
    mesa_build_info: str | None,
    radv_build_info: str | None,
    aco_variant_tag: str | None,
    compiler_variant_tag: str | None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    session_id = build_session_id(game_slug, scene_slug, timestamp=timestamp)
    root = session_root(game_slug, session_id)
    paths = session_paths(root)

    for key, path in paths.items():
        if key.endswith("_dir") or key.endswith("_root"):
            ensure_dir(path)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "session_id": session_id,
        "created_at": now_utc_iso(),
        "updated_at": now_utc_iso(),
        "game_slug": slugify(game_slug),
        "scene_slug": slugify(scene_slug),
        "graphics_settings_profile": settings_profile,
        "expected_comparison_cohort": comparison_cohort,
        "session_root": str(root.resolve()),
        "game_config_path": repo_relative(game_config_path(game_slug)),
        "toolchain": {
            "proton_version": proton_version or "",
            "mesa_build_info": mesa_build_info or "",
            "radv_build_info": radv_build_info or "",
            "aco_variant_tag": aco_variant_tag or "",
            "compiler_variant_tag": compiler_variant_tag or "",
        },
        "operator_context": {
            "operator_notes_summary": operator_notes,
            "capture_window_notes": "",
        },
        "status": {
            "track_a": "prepared_pending_capture",
            "track_b": "awaiting_foz_registration",
            "track_c": "awaiting_optional_inputs",
        },
        "manifests": {
            "session_manifest": repo_relative(paths["session_manifest"]),
            "artifact_registry": repo_relative(paths["artifact_registry"]),
            "track_a_manifest": repo_relative(paths["track_a_manifest"]),
            "track_b_manifest": repo_relative(paths["track_b_manifest"]),
            "track_c_manifest": repo_relative(paths["track_c_manifest"]),
        },
    }

    capture_environment = {
        "session_id": session_id,
        "game_slug": slugify(game_slug),
        "scene_slug": slugify(scene_slug),
        "captured_at": "",
        "graphics_settings_profile": settings_profile,
        "steam_appid": "",
        "steam_launch_options": "",
        "proton_version": proton_version or "",
        "mesa_build_info": mesa_build_info or "",
        "radv_build_info": radv_build_info or "",
        "aco_variant_tag": aco_variant_tag or "",
        "compiler_variant_tag": compiler_variant_tag or "",
        "kernel_version": "",
        "mesa_debug_flags": "",
        "notes": [],
    }

    write_json(paths["session_manifest"], manifest)
    write_json(paths["artifact_registry"], default_artifact_registry(session_id))
    write_json(paths["track_a_manifest"], default_track_manifest(session_id, "track_a"))
    write_json(paths["track_b_manifest"], default_track_manifest(session_id, "track_b"))
    write_json(paths["track_c_manifest"], default_track_manifest(session_id, "track_c"))
    write_json(paths["capture_environment"], capture_environment)
    write_json(paths["tool_resolution"], default_tool_resolution())

    write_text(
        paths["operator_notes"],
        "\n".join(
            [
                f"# Operator Notes for {session_id}",
                "",
                operator_notes or "Fill in what the operator observed during capture.",
                "",
                "## Immediate Follow-up",
                "",
                "- Record anything that might affect reproducibility.",
            ]
        ),
    )
    write_text(
        paths["scene_description"],
        "\n".join(
            [
                f"# Scene Description for {session_id}",
                "",
                "Describe the exact camera position, time of day, NPC state, motion, and any scene-specific triggers.",
                "",
                "## Stable Reference Points",
                "",
                "- Camera anchor:",
                "- Major visible objects:",
                "- Trigger or transition state:",
            ]
        ),
    )
    write_text(
        paths["hypotheses"],
        "\n".join(
            [
                f"# Hypotheses for {session_id}",
                "",
                "Use this file to note expected RDNA3 vs RDNA2-era behavior and later ACO before/after hypotheses.",
                "",
                "## Candidate Explanations",
                "",
                "- Occupancy / wave pressure:",
                "- VGPR or SGPR pressure:",
                "- Scheduling / latency hiding:",
                "- Instruction mix / VALU / VOPD:",
                "- Runtime or pipeline cache behavior:",
            ]
        ),
    )
    write_text(
        paths["session_export"],
        "\n".join(
            [
                f"# Thesis Session Summary: {session_id}",
                "",
                "Run Track C correlation to populate this export with a thesis-ready summary.",
            ]
        ),
    )
    write_text(
        paths["manual_annotation_template"],
        "{\n"
        '  "session_id": "' + session_id + '",\n'
        '  "notes": "Add manual linkage between RenderDoc observations and Fossilize objects.",\n'
        '  "pipeline_hashes": [],\n'
        '  "shader_module_hashes": [],\n'
        '  "draw_call_refs": [],\n'
        '  "confidence": "strong"\n'
        "}\n",
    )
    return {"session_id": session_id, "session_root": root, "paths": paths}


def load_session_manifest(root: Path) -> dict:
    return read_json(session_paths(root)["session_manifest"])


def save_session_manifest(root: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_utc_iso()
    write_json(session_paths(root)["session_manifest"], manifest)


def load_track_manifest(root: Path, track_key: str) -> dict:
    return read_json(session_paths(root)[f"{track_key}_manifest"])


def save_track_manifest(root: Path, track_key: str, manifest: dict) -> None:
    manifest["updated_at"] = now_utc_iso()
    write_json(session_paths(root)[f"{track_key}_manifest"], manifest)


def load_artifact_registry(root: Path) -> dict:
    return read_json(session_paths(root)["artifact_registry"])


def save_artifact_registry(root: Path, registry: dict) -> None:
    registry["updated_at"] = now_utc_iso()
    write_json(session_paths(root)["artifact_registry"], registry)


def update_track_status(root: Path, track_key: str, status: str) -> None:
    manifest = load_session_manifest(root)
    manifest["status"][TRACK_STATUS_KEYS[track_key]] = status
    save_session_manifest(root, manifest)


def append_command_record(root: Path, track_key: str, command: list[str], tool_path: str | None) -> None:
    manifest = load_track_manifest(root, track_key)
    manifest["commands"].append(
        {
            "recorded_at": now_utc_iso(),
            "command": command,
            "tool_path": tool_path or "",
        }
    )
    save_track_manifest(root, track_key, manifest)


def update_tool_resolution(root: Path, reports: dict[str, dict]) -> None:
    path = session_paths(root)["tool_resolution"]
    payload = read_json(path)
    payload["updated_at"] = now_utc_iso()
    payload["tools"].update(reports)
    write_json(path, payload)


def record_artifact(
    root: Path,
    *,
    track_key: str,
    kind: str,
    canonical_path: Path,
    source_path: Path | None,
    label: str,
    metadata: dict | None = None,
    provenance: dict | None = None,
    generated: bool = False,
) -> dict:
    registry = load_artifact_registry(root)
    track_manifest = load_track_manifest(root, track_key)
    file_info = file_metadata(canonical_path)
    artifact_id = f"{track_key}__{kind}__{file_info['sha256'][:12]}"
    entry = {
        "artifact_id": artifact_id,
        "session_id": load_session_manifest(root)["session_id"],
        "track": track_key,
        "kind": kind,
        "label": label,
        "generated": generated,
        "registered_at": now_utc_iso(),
        "source_path": str(source_path.resolve()) if source_path else "",
        "provenance": provenance or {},
        "metadata": metadata or {},
        **file_info,
    }

    artifacts = [artifact for artifact in registry["artifacts"] if artifact["artifact_id"] != artifact_id]
    artifacts.append(entry)
    registry["artifacts"] = sorted(artifacts, key=lambda item: item["artifact_id"])
    save_artifact_registry(root, registry)

    key = "generated_outputs" if generated else "registered_artifacts"
    values = [value for value in track_manifest[key] if value != artifact_id]
    values.append(artifact_id)
    track_manifest[key] = values
    save_track_manifest(root, track_key, track_manifest)
    return entry


def import_artifact(
    root: Path,
    *,
    track_key: str,
    kind: str,
    source_path: Path,
    destination_dir: Path,
    label: str,
    metadata: dict | None = None,
    provenance: dict | None = None,
) -> dict:
    copied_path = copy_file(source_path, destination_dir)
    return record_artifact(
        root,
        track_key=track_key,
        kind=kind,
        canonical_path=copied_path,
        source_path=source_path,
        label=label,
        metadata=metadata,
        provenance=provenance,
        generated=False,
    )


def locate_session(session_id: str) -> Path:
    matches = list(ANALYSIS_ROOT.glob(f"games/*/sessions/{session_id}"))
    if not matches:
        raise FileNotFoundError(f"Session not found: {session_id}")
    if len(matches) > 1:
        raise RuntimeError(f"Session id is ambiguous: {session_id}")
    return matches[0]


def resolve_session_reference(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    return locate_session(value)

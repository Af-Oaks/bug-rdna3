"""Register Track A manual capture artifacts into the canonical session layout."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.analysis_pipeline.common.session_lib import (
    append_command_record,
    import_artifact,
    load_track_manifest,
    resolve_session_reference,
    save_track_manifest,
    session_paths,
    update_track_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session id or absolute session path")
    parser.add_argument("--rdc", action="append", default=[], help="Path to a RenderDoc .rdc capture")
    parser.add_argument("--screenshot", action="append", default=[], help="Path to a screenshot")
    parser.add_argument("--draw-summary", action="append", default=[], help="Path to draw summary export")
    parser.add_argument("--frame-marker-file", action="append", default=[], help="Path to frame marker export")
    parser.add_argument("--log-file", action="append", default=[], help="Path to capture-side log")
    parser.add_argument("--note-file", action="append", default=[], help="Additional note file to preserve")
    return parser


def register_many(
    session_root: Path,
    sources: list[str],
    *,
    track_key: str,
    kind: str,
    destination_dir: Path,
) -> list[str]:
    artifact_ids = []
    for source in sources:
        entry = import_artifact(
            session_root,
            track_key=track_key,
            kind=kind,
            source_path=Path(source).expanduser().resolve(),
            destination_dir=destination_dir,
            label=Path(source).name,
            provenance={"import_method": "manual_registration"},
        )
        artifact_ids.append(entry["artifact_id"])
        print(f"Registered {kind}: {entry['canonical_path']}")
    return artifact_ids


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)

    all_artifacts = []
    all_artifacts.extend(
        register_many(session_root, args.rdc, track_key="track_a", kind="renderdoc_capture", destination_dir=paths["track_a_renderdoc_dir"])
    )
    all_artifacts.extend(
        register_many(session_root, args.screenshot, track_key="track_a", kind="scene_screenshot", destination_dir=paths["track_a_screenshots_dir"])
    )
    all_artifacts.extend(
        register_many(session_root, args.draw_summary, track_key="track_a", kind="draw_summary", destination_dir=paths["track_a_frame_markers_dir"])
    )
    all_artifacts.extend(
        register_many(session_root, args.frame_marker_file, track_key="track_a", kind="frame_marker_export", destination_dir=paths["track_a_frame_markers_dir"])
    )
    all_artifacts.extend(
        register_many(session_root, args.log_file, track_key="track_a", kind="capture_log", destination_dir=paths["track_a_logs_dir"])
    )
    all_artifacts.extend(
        register_many(session_root, args.note_file, track_key="track_a", kind="manual_note_attachment", destination_dir=paths["notes_dir"])
    )

    track_manifest = load_track_manifest(session_root, "track_a")
    track_manifest["status"] = "capture_artifacts_registered" if all_artifacts else track_manifest["status"]
    save_track_manifest(session_root, "track_a", track_manifest)
    if all_artifacts:
        update_track_status(session_root, "track_a", "capture_artifacts_registered")
    append_command_record(session_root, "track_a", ["register_capture.py", "--session", args.session], None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

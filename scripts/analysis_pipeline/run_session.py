"""Register in-place session artifacts and run the remaining pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.analysis_pipeline.common.session_lib import (
    append_command_record,
    load_track_manifest,
    record_artifact,
    resolve_session_reference,
    session_paths,
    update_track_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session id or absolute session path")
    parser.add_argument(
        "--skip-correlation",
        action="store_true",
        help="Only register artifacts and run Track B mining",
    )
    parser.add_argument(
        "--run-legacy-extract",
        action="store_true",
        help="Also run the legacy extract.py wrapper during Track C correlation",
    )
    return parser


def collect_files(directory: Path, pattern: str = "*") -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def register_in_place(
    session_root: Path,
    *,
    track_key: str,
    kind: str,
    paths: list[Path],
    extra_metadata: dict | None = None,
) -> int:
    count = 0
    for path in paths:
        record_artifact(
            session_root,
            track_key=track_key,
            kind=kind,
            canonical_path=path,
            source_path=path,
            label=path.name,
            metadata=extra_metadata or {},
            provenance={"import_method": "in_place_session_scan", "runner": "run_session.py"},
            generated=False,
        )
        count += 1
    return count


def register_track_a(session_root: Path, paths: dict[str, Path]) -> int:
    count = 0
    count += register_in_place(
        session_root,
        track_key="track_a",
        kind="renderdoc_capture",
        paths=collect_files(paths["track_a_renderdoc_dir"]),
    )
    count += register_in_place(
        session_root,
        track_key="track_a",
        kind="scene_screenshot",
        paths=collect_files(paths["track_a_screenshots_dir"]),
    )
    frame_marker_files = collect_files(paths["track_a_frame_markers_dir"])
    draw_summary_files = [path for path in frame_marker_files if "draw" in path.name.lower()]
    marker_files = [path for path in frame_marker_files if path not in draw_summary_files]
    count += register_in_place(
        session_root,
        track_key="track_a",
        kind="draw_summary",
        paths=draw_summary_files,
    )
    count += register_in_place(
        session_root,
        track_key="track_a",
        kind="frame_marker_export",
        paths=marker_files,
    )
    count += register_in_place(
        session_root,
        track_key="track_a",
        kind="capture_log",
        paths=collect_files(paths["track_a_logs_dir"]),
    )
    if count:
        track_manifest = load_track_manifest(session_root, "track_a")
        track_manifest["status"] = "capture_artifacts_registered"
        from scripts.analysis_pipeline.common.session_lib import save_track_manifest

        save_track_manifest(session_root, "track_a", track_manifest)
        update_track_status(session_root, "track_a", "capture_artifacts_registered")
    return count


def register_track_b_inputs(session_root: Path, paths: dict[str, Path]) -> int:
    count = register_in_place(
        session_root,
        track_key="track_b",
        kind="fossilize_database",
        paths=collect_files(paths["track_b_inputs_dir"], "*.foz"),
    )
    if count:
        track_manifest = load_track_manifest(session_root, "track_b")
        track_manifest["status"] = "foz_registered"
        from scripts.analysis_pipeline.common.session_lib import save_track_manifest

        save_track_manifest(session_root, "track_b", track_manifest)
        update_track_status(session_root, "track_b", "foz_registered")
    return count


def register_track_c_inputs(session_root: Path, paths: dict[str, Path]) -> int:
    count = 0
    count += register_in_place(
        session_root,
        track_key="track_c",
        kind="isa_dump",
        paths=collect_files(paths["track_c_isa_dir"]),
    )
    count += register_in_place(
        session_root,
        track_key="track_c",
        kind="compiler_log",
        paths=collect_files(paths["track_c_compiler_logs_dir"]),
    )
    count += register_in_place(
        session_root,
        track_key="track_c",
        kind="rga_report",
        paths=collect_files(paths["track_c_rga_dir"]),
    )
    count += register_in_place(
        session_root,
        track_key="track_c",
        kind="profiling_artifact",
        paths=collect_files(paths["track_c_profiling_dir"]),
    )
    count += register_in_place(
        session_root,
        track_key="track_c",
        kind="manual_annotation",
        paths=collect_files(paths["track_c_annotations_dir"]),
    )
    if paths["manual_annotation_template"].exists():
        count += register_in_place(
            session_root,
            track_key="track_c",
            kind="manual_annotation",
            paths=[paths["manual_annotation_template"]],
            extra_metadata={"role": "session_root_annotation"},
        )
    if count:
        track_manifest = load_track_manifest(session_root, "track_c")
        track_manifest["status"] = "optional_inputs_registered"
        from scripts.analysis_pipeline.common.session_lib import save_track_manifest

        save_track_manifest(session_root, "track_c", track_manifest)
        update_track_status(session_root, "track_c", "optional_inputs_registered")
    return count


def run_module(module_name: str, *args: str) -> None:
    command = [sys.executable, "-m", module_name, *args]
    subprocess.run(command, check=True)


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)

    track_a_count = register_track_a(session_root, paths)
    track_b_count = register_track_b_inputs(session_root, paths)
    track_c_count = register_track_c_inputs(session_root, paths)

    print(f"Track A in-place artifacts registered: {track_a_count}")
    print(f"Track B in-place `.foz` registered: {track_b_count}")
    print(f"Track C optional artifacts registered: {track_c_count}")

    if track_b_count == 0:
        raise RuntimeError(
            f"No `.foz` files found in {paths['track_b_inputs_dir']}. "
            "Place the `.foz` inside the session folder before running this command."
        )

    append_command_record(session_root, "track_b", ["run_session.py", "--session", args.session], None)
    run_module("scripts.analysis_pipeline.track_b.mine_pipelines", "--session", session_root.name)

    if not args.skip_correlation:
        correlate_args = ["--session", session_root.name]
        if args.run_legacy_extract:
            correlate_args.append("--run-legacy-extract")
        append_command_record(session_root, "track_c", ["run_session.py", "--session", args.session], None)
        run_module("scripts.analysis_pipeline.track_c.correlate_session", *correlate_args)

    print(f"Finished session pipeline: {session_root.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

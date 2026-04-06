"""Register optional Track C artifacts such as ISA dumps, RGA outputs, and profiling files."""

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
    parser.add_argument("--isa-file", action="append", default=[], help="Optional ISA dump file")
    parser.add_argument("--compiler-log", action="append", default=[], help="Optional compiler log")
    parser.add_argument("--rga-report", action="append", default=[], help="Optional RGA report")
    parser.add_argument("--profiling-file", action="append", default=[], help="Optional RGP/SQTT or profiling file")
    parser.add_argument("--manual-annotation", action="append", default=[], help="Optional manual annotation file")
    return parser


def register_group(session_root: Path, inputs: list[str], *, kind: str, destination_dir: Path) -> list[str]:
    artifact_ids = []
    for raw_path in inputs:
        source = Path(raw_path).expanduser().resolve()
        entry = import_artifact(
            session_root,
            track_key="track_c",
            kind=kind,
            source_path=source,
            destination_dir=destination_dir,
            label=source.name,
            provenance={"import_method": "manual_registration"},
        )
        artifact_ids.append(entry["artifact_id"])
        print(f"Registered {kind}: {entry['canonical_path']}")
    return artifact_ids


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)
    artifact_ids = []
    artifact_ids.extend(register_group(session_root, args.isa_file, kind="isa_dump", destination_dir=paths["track_c_isa_dir"]))
    artifact_ids.extend(
        register_group(session_root, args.compiler_log, kind="compiler_log", destination_dir=paths["track_c_compiler_logs_dir"])
    )
    artifact_ids.extend(register_group(session_root, args.rga_report, kind="rga_report", destination_dir=paths["track_c_rga_dir"]))
    artifact_ids.extend(
        register_group(session_root, args.profiling_file, kind="profiling_artifact", destination_dir=paths["track_c_profiling_dir"])
    )
    artifact_ids.extend(
        register_group(session_root, args.manual_annotation, kind="manual_annotation", destination_dir=paths["track_c_annotations_dir"])
    )

    track_manifest = load_track_manifest(session_root, "track_c")
    if artifact_ids:
        track_manifest["status"] = "optional_inputs_registered"
        save_track_manifest(session_root, "track_c", track_manifest)
        update_track_status(session_root, "track_c", "optional_inputs_registered")
    append_command_record(
        session_root,
        "track_c",
        ["register_optional_artifacts.py", "--session", args.session],
        None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Register `.foz` inputs for a session."""

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
    parser.add_argument("--foz", action="append", required=True, help="Path to a `.foz` file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)
    artifact_ids = []
    for foz_path in args.foz:
        source = Path(foz_path).expanduser().resolve()
        entry = import_artifact(
            session_root,
            track_key="track_b",
            kind="fossilize_database",
            source_path=source,
            destination_dir=paths["track_b_inputs_dir"],
            label=source.name,
            provenance={"import_method": "manual_registration"},
        )
        artifact_ids.append(entry["artifact_id"])
        print(f"Registered .foz: {entry['canonical_path']}")

    track_manifest = load_track_manifest(session_root, "track_b")
    track_manifest["status"] = "foz_registered"
    save_track_manifest(session_root, "track_b", track_manifest)
    update_track_status(session_root, "track_b", "foz_registered")
    append_command_record(session_root, "track_b", ["register_foz.py", "--session", args.session], None)
    print(f"Registered {len(artifact_ids)} Fossilize database(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

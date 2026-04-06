"""Prepare Track A instructions and tool resolution for a session."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.analysis_pipeline.common.io_utils import repo_relative, write_text
from scripts.analysis_pipeline.common.session_lib import (
    append_command_record,
    load_game_config,
    load_track_manifest,
    resolve_session_reference,
    save_track_manifest,
    session_paths,
    update_tool_resolution,
)
from scripts.analysis_pipeline.common.tools import format_tool_report, resolve_many


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session id or absolute session path")
    return parser


def render_instructions(session_id: str, game_config: dict, paths: dict, tool_reports: dict[str, dict]) -> str:
    scene_labels = ", ".join(game_config.get("scene_labels", [])) or "<define in config>"
    foz_patterns = "\n".join(f"- `{pattern}`" for pattern in game_config.get("expected_foz_location_patterns", []))
    if not foz_patterns:
        foz_patterns = "- Preserve the `.foz` files generated during the same scene/session window."

    launch_options = "\n".join(f"- `{item}`" for item in game_config.get("recommended_launch_options", []))
    if not launch_options:
        launch_options = "- Define launch options in the per-game config before capture."

    capture_notes = "\n".join(f"- {item}" for item in game_config.get("capture_notes", []))
    if not capture_notes:
        capture_notes = "- Use RenderDoc manually and record the exact frame/time."

    tool_lines = "\n".join(f"- {format_tool_report(report)}" for report in tool_reports.values())

    return "\n".join(
        [
            f"# Track A Capture Instructions for {session_id}",
            "",
            "## Tool Resolution",
            "",
            tool_lines,
            "",
            "## Capture Order",
            "",
            "1. Launch the game with the configured Proton and graphics settings profile.",
            "2. Reach the named scene and stabilize camera / motion before capture.",
            "3. Trigger a RenderDoc frame capture manually.",
            "4. Save at least one screenshot that clearly identifies the scene state.",
            "5. Record manual notes about camera anchor, movement, NPC state, and any transient effects.",
            "6. Preserve the `.foz` files generated from the same session window for Track B.",
            "",
            "## Per-Game Scene Hints",
            "",
            f"- Known scene labels: {scene_labels}",
            f"- Proton notes: {game_config.get('proton_notes', 'Add Proton-specific capture notes here.')}",
            f"- Executable notes: {game_config.get('executable_notes', 'Document executable and Steam launch path details here.')}",
            "",
            "## Recommended Launch Options",
            "",
            launch_options,
            "",
            "## Manual Capture Notes",
            "",
            capture_notes,
            "",
            "## Expected Canonical Session Slots",
            "",
            f"- RenderDoc captures: `{repo_relative(paths['track_a_renderdoc_dir'])}`",
            f"- Screenshots: `{repo_relative(paths['track_a_screenshots_dir'])}`",
            f"- Frame markers / draw summaries: `{repo_relative(paths['track_a_frame_markers_dir'])}`",
            f"- Capture logs: `{repo_relative(paths['track_a_logs_dir'])}`",
            "",
            "## Expected `.foz` Collection Patterns",
            "",
            foz_patterns,
            "",
            "## Honest Limitations",
            "",
            "- This workflow prepares metadata and canonical storage; it does not automate in-game navigation.",
            "- It does not assume RenderDoc can be fully automated through Proton for every title.",
            "- Exact Track A to Track B pipeline matching remains unresolved until explicit hashes or manual annotations are imported.",
        ]
    )


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    session_manifest = session_paths(session_root)["session_manifest"]
    session_id = session_manifest.parent.joinpath("..").resolve().name
    game_config = load_game_config(session_root.parent.parent.name)
    paths = session_paths(session_root)
    tool_reports = resolve_many("renderdoccmd", "qrenderdoc")
    update_tool_resolution(session_root, tool_reports)

    instructions = render_instructions(session_root.name, game_config, paths, tool_reports)
    write_text(paths["track_a_instructions"], instructions)

    track_manifest = load_track_manifest(session_root, "track_a")
    track_manifest["status"] = "prepared_pending_manual_capture"
    track_manifest["expected_outputs"] = {
        "renderdoc_dir": repo_relative(paths["track_a_renderdoc_dir"]),
        "screenshots_dir": repo_relative(paths["track_a_screenshots_dir"]),
        "frame_markers_dir": repo_relative(paths["track_a_frame_markers_dir"]),
        "logs_dir": repo_relative(paths["track_a_logs_dir"]),
        "instructions": repo_relative(paths["track_a_instructions"]),
    }
    track_manifest["notes"].append(
        "Track A uses RenderDoc as the primary real-frame capture path. Manual capture is expected."
    )
    save_track_manifest(session_root, "track_a", track_manifest)
    append_command_record(session_root, "track_a", ["prepare_capture.py", "--session", args.session], None)

    for report in tool_reports.values():
        print(format_tool_report(report))
    print(f"Wrote instructions: {paths['track_a_instructions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

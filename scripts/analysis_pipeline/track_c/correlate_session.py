"""Build Track C correlation outputs for a session."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.analysis_pipeline.common.io_utils import extract_hex_tokens_from_path, repo_relative, write_csv, write_json, write_text
from scripts.analysis_pipeline.common.legacy_extract import run_legacy_extract
from scripts.analysis_pipeline.common.session_lib import (
    append_command_record,
    load_artifact_registry,
    load_session_manifest,
    load_track_manifest,
    record_artifact,
    resolve_session_reference,
    save_track_manifest,
    session_paths,
    update_track_status,
)
from scripts.analysis_pipeline.common.tools import format_tool_report, resolve_many


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session id or absolute session path")
    parser.add_argument(
        "--run-legacy-extract",
        action="store_true",
        help="Run the root extract.py helper on registered compiler logs when possible",
    )
    return parser


def load_generated_json(track_manifest: dict, registry_by_id: dict[str, dict], kind: str) -> list | dict:
    for artifact_id in track_manifest["generated_outputs"]:
        artifact = registry_by_id.get(artifact_id)
        if artifact and artifact["kind"] == kind:
            return Path(artifact["canonical_path"]).read_text(encoding="utf-8")
    raise FileNotFoundError(f"Generated output not found for kind: {kind}")


def compute_confidence(
    pipeline_hash: str,
    linked_shader_modules: list[str],
    matching_artifacts: list[dict],
    has_track_a_capture: bool,
) -> tuple[str, list[str]]:
    basis = []
    if any(pipeline_hash in artifact["hash_tokens"] for artifact in matching_artifacts):
        basis.append("exact_pipeline_hash")
        return "exact", basis
    if any(set(linked_shader_modules) & set(artifact["hash_tokens"]) for artifact in matching_artifacts):
        basis.append("linked_shader_module_hash")
        return "strong", basis
    if has_track_a_capture:
        basis.append("same_session_id")
        basis.append("same_scene_slug")
        return "weak", basis
    return "unresolved", ["no_hash_match"]


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)
    tool_reports = resolve_many("rga", "rgp")
    for report in tool_reports.values():
        print(format_tool_report(report))

    session_manifest = load_session_manifest(session_root)
    registry = load_artifact_registry(session_root)
    registry_by_id = {artifact["artifact_id"]: artifact for artifact in registry["artifacts"]}
    track_a_manifest = load_track_manifest(session_root, "track_a")
    track_b_manifest = load_track_manifest(session_root, "track_b")
    track_c_manifest = load_track_manifest(session_root, "track_c")

    pipelines_summary_path = paths["track_b_summaries_dir"] / "pipelines_summary.json"
    shader_summary_path = paths["track_b_summaries_dir"] / "shader_modules_summary.json"
    if not pipelines_summary_path.exists() or not shader_summary_path.exists():
        raise RuntimeError("Track B summaries are required before running correlation.")

    pipelines = __import__("json").loads(pipelines_summary_path.read_text(encoding="utf-8"))
    shader_modules = __import__("json").loads(shader_summary_path.read_text(encoding="utf-8"))
    shader_lookup = {module["shader_module_hash"]: module for module in shader_modules}

    optional_artifacts = []
    for artifact_id in track_c_manifest["registered_artifacts"]:
        artifact = registry_by_id.get(artifact_id)
        if artifact is None:
            continue
        canonical_path = Path(artifact["canonical_path"])
        tokens = extract_hex_tokens_from_path(canonical_path)
        optional_artifacts.append(
            {
                **artifact,
                "hash_tokens": tokens,
            }
        )

    legacy_extract_outputs = []
    if args.run_legacy_extract:
        for artifact in optional_artifacts:
            if artifact["kind"] != "compiler_log":
                continue
            output_json = paths["track_c_outputs_dir"] / f"{Path(artifact['canonical_path']).stem}__legacy_extract.json"
            result = run_legacy_extract(Path(artifact["canonical_path"]), output_json)
            legacy_extract_outputs.append(result)
            if result["status"] == "ok":
                record_artifact(
                    session_root,
                    track_key="track_c",
                    kind="legacy_extract_samples",
                    canonical_path=output_json,
                    source_path=None,
                    label=output_json.name,
                    metadata={"source_compiler_log_artifact_id": artifact["artifact_id"]},
                    provenance={"generated_by": "correlate_session.py", "wrapper": "extract.py"},
                    generated=True,
                )

    has_track_a_capture = any(
        registry_by_id.get(artifact_id, {}).get("kind") == "renderdoc_capture"
        for artifact_id in track_a_manifest["registered_artifacts"]
    )

    correlation_rows = []
    unresolved_matches = []
    for pipeline in pipelines:
        matching_artifacts = []
        for artifact in optional_artifacts:
            if pipeline["pipeline_hash"] in artifact["hash_tokens"]:
                matching_artifacts.append(artifact)
                continue
            if set(pipeline["linked_shader_modules"]) & set(artifact["hash_tokens"]):
                matching_artifacts.append(artifact)

        confidence, basis = compute_confidence(
            pipeline["pipeline_hash"],
            pipeline["linked_shader_modules"],
            matching_artifacts,
            has_track_a_capture,
        )
        correlation_entry = {
            "session_id": session_manifest["session_id"],
            "game_slug": session_manifest["game_slug"],
            "scene_slug": session_manifest["scene_slug"],
            "pipeline_hash": pipeline["pipeline_hash"],
            "pipeline_type": pipeline["pipeline_type"],
            "linked_shader_modules": pipeline["linked_shader_modules"],
            "shader_stage_status": pipeline["stage_info"]["status"],
            "matching_artifact_ids": [artifact["artifact_id"] for artifact in matching_artifacts],
            "matching_isa_artifacts": [
                artifact["artifact_id"] for artifact in matching_artifacts if artifact["kind"] == "isa_dump"
            ],
            "matching_compiler_logs": [
                artifact["artifact_id"] for artifact in matching_artifacts if artifact["kind"] == "compiler_log"
            ],
            "matching_rga_reports": [
                artifact["artifact_id"] for artifact in matching_artifacts if artifact["kind"] == "rga_report"
            ],
            "matching_profile_artifacts": [
                artifact["artifact_id"] for artifact in matching_artifacts if artifact["kind"] == "profiling_artifact"
            ],
            "analysis_confidence": confidence,
            "match_basis": basis,
            "compiler_variant_tag": session_manifest["toolchain"].get("compiler_variant_tag", ""),
            "aco_variant_tag": session_manifest["toolchain"].get("aco_variant_tag", ""),
            "notes": "",
            "future_comparison_placeholders": {
                "baseline_compiler_tag": "baseline",
                "modified_aco_tag": session_manifest["toolchain"].get("aco_variant_tag", "modified_aco"),
                "expected_delta_axes": [
                    "occupancy",
                    "vgpr_pressure",
                    "sgpr_pressure",
                    "scheduling",
                    "instruction_mix",
                    "cache_or_runtime_effects",
                ],
            },
        }
        correlation_rows.append(correlation_entry)
        if confidence == "unresolved":
            unresolved_matches.append(correlation_entry)

    correlation_summary = {
        "session_id": session_manifest["session_id"],
        "game_slug": session_manifest["game_slug"],
        "scene_slug": session_manifest["scene_slug"],
        "track_a_capture_present": has_track_a_capture,
        "pipeline_count": len(pipelines),
        "shader_module_count": len(shader_modules),
        "optional_artifact_count": len(optional_artifacts),
        "confidence_counts": {
            "exact": sum(1 for row in correlation_rows if row["analysis_confidence"] == "exact"),
            "strong": sum(1 for row in correlation_rows if row["analysis_confidence"] == "strong"),
            "weak": sum(1 for row in correlation_rows if row["analysis_confidence"] == "weak"),
            "unresolved": sum(1 for row in correlation_rows if row["analysis_confidence"] == "unresolved"),
        },
        "legacy_extract_runs": legacy_extract_outputs,
        "tool_resolution": tool_reports,
        "notes": [
            "Exact correlation requires shared identifiers such as pipeline hashes, shader hashes, or explicit manual annotation.",
            "Weak confidence only means same-session linkage exists; it does not prove a specific pipeline was visible in the captured frame.",
        ],
    }

    summary_md = "\n".join(
        [
            f"# Correlation Summary for {session_manifest['session_id']}",
            "",
            f"- Game: `{session_manifest['game_slug']}`",
            f"- Scene: `{session_manifest['scene_slug']}`",
            f"- Track A capture present: `{has_track_a_capture}`",
            f"- Pipelines mined: `{len(pipelines)}`",
            f"- Shader modules mined: `{len(shader_modules)}`",
            f"- Optional artifacts registered: `{len(optional_artifacts)}`",
            "",
            "## Confidence Counts",
            "",
            f"- exact: `{correlation_summary['confidence_counts']['exact']}`",
            f"- strong: `{correlation_summary['confidence_counts']['strong']}`",
            f"- weak: `{correlation_summary['confidence_counts']['weak']}`",
            f"- unresolved: `{correlation_summary['confidence_counts']['unresolved']}`",
            "",
            "## Next Steps",
            "",
            "- Import RenderDoc draw summaries or manual annotations to upgrade weak/unresolved linkage.",
            "- Register ISA/RGA/profiling artifacts from the same capture window to strengthen pipeline-level evidence.",
            "- Use the placeholders in the CSV/JSON outputs for baseline vs modified ACO comparison later.",
        ]
    )

    outputs = {
        "correlation_summary_json": paths["track_c_outputs_dir"] / "correlation_summary.json",
        "correlation_summary_md": paths["track_c_outputs_dir"] / "correlation_summary.md",
        "pipeline_correlation_csv": paths["track_c_outputs_dir"] / "pipeline_correlation_table.csv",
        "unresolved_matches_json": paths["track_c_outputs_dir"] / "unresolved_matches.json",
    }
    write_json(outputs["correlation_summary_json"], correlation_summary)
    write_text(outputs["correlation_summary_md"], summary_md)
    write_csv(
        outputs["pipeline_correlation_csv"],
        [
            {
                "session_id": row["session_id"],
                "game_slug": row["game_slug"],
                "scene_slug": row["scene_slug"],
                "pipeline_hash": row["pipeline_hash"],
                "pipeline_type": row["pipeline_type"],
                "linked_shader_modules": ";".join(row["linked_shader_modules"]),
                "analysis_confidence": row["analysis_confidence"],
                "match_basis": ";".join(row["match_basis"]),
                "matching_artifact_ids": ";".join(row["matching_artifact_ids"]),
                "compiler_variant_tag": row["compiler_variant_tag"],
                "aco_variant_tag": row["aco_variant_tag"],
            }
            for row in correlation_rows
        ],
        fieldnames=[
            "session_id",
            "game_slug",
            "scene_slug",
            "pipeline_hash",
            "pipeline_type",
            "linked_shader_modules",
            "analysis_confidence",
            "match_basis",
            "matching_artifact_ids",
            "compiler_variant_tag",
            "aco_variant_tag",
        ],
    )
    write_json(outputs["unresolved_matches_json"], unresolved_matches)

    export_summary = "\n".join(
        [
            f"# Thesis Session Summary: {session_manifest['session_id']}",
            "",
            f"- Game / scene: `{session_manifest['game_slug']}` / `{session_manifest['scene_slug']}`",
            f"- Comparison cohort: `{session_manifest['expected_comparison_cohort']}`",
            f"- Compiler tag: `{session_manifest['toolchain'].get('compiler_variant_tag', '')}`",
            f"- ACO variant: `{session_manifest['toolchain'].get('aco_variant_tag', '')}`",
            "",
            "## Evidence Snapshot",
            "",
            f"- RenderDoc capture present: `{has_track_a_capture}`",
            f"- Track B pipelines: `{len(pipelines)}`",
            f"- Exact correlations: `{correlation_summary['confidence_counts']['exact']}`",
            f"- Strong correlations: `{correlation_summary['confidence_counts']['strong']}`",
            f"- Weak correlations: `{correlation_summary['confidence_counts']['weak']}`",
            f"- Unresolved correlations: `{correlation_summary['confidence_counts']['unresolved']}`",
            "",
            "## Thesis Use",
            "",
            "- Use this session alongside comparable sessions from high-gain and low-gain cohorts.",
            "- Add before/after compiler artifacts later to compare occupancy, register pressure, scheduling, and instruction mix deltas.",
        ]
    )
    write_text(paths["session_export"], export_summary)

    for output_name, output_path in outputs.items():
        record_artifact(
            session_root,
            track_key="track_c",
            kind=output_name,
            canonical_path=output_path,
            source_path=None,
            label=output_path.name,
            metadata={"output_type": output_name},
            provenance={"generated_by": "correlate_session.py"},
            generated=True,
        )
    record_artifact(
        session_root,
        track_key="track_c",
        kind="session_export_markdown",
        canonical_path=paths["session_export"],
        source_path=None,
        label=paths["session_export"].name,
        metadata={"output_type": "export_summary"},
        provenance={"generated_by": "correlate_session.py"},
        generated=True,
    )

    track_c_manifest["status"] = "correlation_complete"
    track_c_manifest["summary_outputs"] = {name: repo_relative(path) for name, path in outputs.items()}
    save_track_manifest(session_root, "track_c", track_c_manifest)
    update_track_status(session_root, "track_c", "correlation_complete")
    append_command_record(session_root, "track_c", ["correlate_session.py", "--session", args.session], None)
    print(f"Wrote correlation outputs: {paths['track_c_outputs_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

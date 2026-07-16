"""Mine normalized pipeline and shader metadata from registered `.foz` inputs."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from scripts.analysis_pipeline.common.constants import FOSSILIZE_TAGS, PIPELINE_TAGS
from scripts.analysis_pipeline.common.io_utils import repo_relative, write_csv, write_json
from scripts.analysis_pipeline.common.session_lib import (
    append_command_record,
    load_artifact_registry,
    load_session_manifest,
    load_track_manifest,
    record_artifact,
    resolve_session_reference,
    save_track_manifest,
    session_paths,
    update_tool_resolution,
    update_track_status,
)
from scripts.analysis_pipeline.common.tools import format_tool_report, resolve_many

SIZE_RE = re.compile(
    r"^(?P<hash>[0-9a-f]+)\s+(?P<compressed>\d+) compressed bytes,\s+(?P<uncompressed>\d+) uncompressed bytes$",
    re.IGNORECASE,
)
CONNECTIVITY_RE = re.compile(r"(?P<label>[A-Za-z]+)\((?P<tag>\d+)\):(?P<hash>[0-9a-f]+)", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session id or absolute session path")
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=20,
        help="How many candidate inspection pipelines to emit",
    )
    return parser


def run_list_command(tool_path: str, foz_path: Path, tag: int, extra_arg: str | None = None) -> str:
    command = [tool_path, str(foz_path), "--tag", str(tag)]
    if extra_arg:
        command.append(extra_arg)
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def parse_plain_hashes(output: str) -> list[str]:
    return [line.strip().lower() for line in output.splitlines() if line.strip() and not line.startswith("Total ")]


def parse_sizes(output: str) -> dict[str, dict]:
    sizes = {}
    for line in output.splitlines():
        match = SIZE_RE.match(line.strip())
        if match:
            sizes[match.group("hash").lower()] = {
                "compressed_size_bytes": int(match.group("compressed")),
                "uncompressed_size_bytes": int(match.group("uncompressed")),
            }
    return sizes


def parse_connectivity(output: str) -> dict[str, list[dict]]:
    connectivity = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        hash_prefix, details = line.split(":", 1)
        object_hash = hash_prefix.strip().lower()
        matches = []
        for match in CONNECTIVITY_RE.finditer(details):
            matches.append(
                {
                    "label": match.group("label"),
                    "tag": int(match.group("tag")),
                    "hash": match.group("hash").lower(),
                }
            )
        connectivity[object_hash] = matches
    return connectivity


def artifact_lookup_by_id(registry: dict) -> dict[str, dict]:
    return {artifact["artifact_id"]: artifact for artifact in registry["artifacts"]}


def main() -> int:
    args = build_parser().parse_args()
    session_root = resolve_session_reference(args.session)
    paths = session_paths(session_root)
    tool_reports = resolve_many("fossilize-list", "fossilize-disasm")
    update_tool_resolution(session_root, tool_reports)
    for report in tool_reports.values():
        print(format_tool_report(report))

    fossilize_list = tool_reports["fossilize-list"]
    if fossilize_list["status"] == "missing":
        raise RuntimeError("fossilize-list is required for Track B mining.")

    track_manifest = load_track_manifest(session_root, "track_b")
    registry = load_artifact_registry(session_root)
    artifact_index = artifact_lookup_by_id(registry)
    foz_artifact_ids = [
        artifact_id
        for artifact_id in track_manifest["registered_artifacts"]
        if artifact_index.get(artifact_id, {}).get("kind") == "fossilize_database"
    ]
    if not foz_artifact_ids:
        raise RuntimeError("No `.foz` artifacts registered for this session.")

    session_manifest = load_session_manifest(session_root)
    shader_modules: dict[str, dict] = {}
    pipelines: dict[str, dict] = {}
    command_records = []

    for artifact_id in foz_artifact_ids:
        artifact = artifact_index[artifact_id]
        foz_path = Path(artifact["canonical_path"])
        for tag in [4, 6, 7, 9]:
            raw_list = run_list_command(fossilize_list["path"], foz_path, tag)
            raw_sizes = run_list_command(fossilize_list["path"], foz_path, tag, "--size")
            raw_connectivity = run_list_command(fossilize_list["path"], foz_path, tag, "--connectivity")
            command_records.append(
                {
                    "tool_path": fossilize_list["path"],
                    "foz_path": str(foz_path),
                    "tag": tag,
                    "commands": [
                        [fossilize_list["path"], str(foz_path), "--tag", str(tag)],
                        [fossilize_list["path"], str(foz_path), "--tag", str(tag), "--size"],
                        [fossilize_list["path"], str(foz_path), "--tag", str(tag), "--connectivity"],
                    ],
                }
            )
            hashes = parse_plain_hashes(raw_list)
            sizes = parse_sizes(raw_sizes)
            connectivity = parse_connectivity(raw_connectivity)

            if tag == 4:
                for shader_hash in hashes:
                    entry = shader_modules.setdefault(
                        shader_hash,
                        {
                            "session_id": session_manifest["session_id"],
                            "shader_module_hash": shader_hash,
                            "fossilize_tag": tag,
                            "object_type": FOSSILIZE_TAGS[tag],
                            "source_foz_artifact_ids": [],
                            "source_foz_paths": [],
                            "linked_pipelines": [],
                            "usage_count": 0,
                            "size_bytes": sizes.get(shader_hash, {}),
                            "connectivity": connectivity.get(shader_hash, []),
                        },
                    )
                    if artifact_id not in entry["source_foz_artifact_ids"]:
                        entry["source_foz_artifact_ids"].append(artifact_id)
                    if artifact["canonical_path"] not in entry["source_foz_paths"]:
                        entry["source_foz_paths"].append(artifact["canonical_path"])
                    if shader_hash in sizes:
                        entry["size_bytes"] = sizes[shader_hash]
                    if shader_hash in connectivity:
                        entry["connectivity"] = connectivity[shader_hash]
            else:
                pipeline_type = PIPELINE_TAGS[tag]
                for pipeline_hash in hashes:
                    linked_shader_modules = [
                        item["hash"]
                        for item in connectivity.get(pipeline_hash, [])
                        if item["tag"] == 4
                    ]
                    layout_hashes = [
                        item["hash"]
                        for item in connectivity.get(pipeline_hash, [])
                        if item["tag"] == 3
                    ]
                    pipeline_entry = pipelines.setdefault(
                        pipeline_hash,
                        {
                            "session_id": session_manifest["session_id"],
                            "pipeline_hash": pipeline_hash,
                            "pipeline_type": pipeline_type,
                            "fossilize_tag": tag,
                            "source_foz_artifact_ids": [],
                            "source_foz_paths": [],
                            "linked_shader_modules": [],
                            "pipeline_layout_hashes": [],
                            "size_bytes": sizes.get(pipeline_hash, {}),
                            "connectivity": connectivity.get(pipeline_hash, []),
                            "track_a_match": {
                                "confidence": "unresolved",
                                "match_basis": ["same_session_id", "same_game_slug", "same_scene_slug"],
                                "notes": "Exact Track A pipeline linkage requires RenderDoc exports or manual annotation.",
                            },
                            "stage_info": {
                                "status": "unresolved",
                                "notes": "Fossilize list output does not expose shader stage mapping directly.",
                            },
                        },
                    )
                    if artifact_id not in pipeline_entry["source_foz_artifact_ids"]:
                        pipeline_entry["source_foz_artifact_ids"].append(artifact_id)
                    if artifact["canonical_path"] not in pipeline_entry["source_foz_paths"]:
                        pipeline_entry["source_foz_paths"].append(artifact["canonical_path"])
                    pipeline_entry["linked_shader_modules"] = sorted(
                        set(pipeline_entry["linked_shader_modules"]) | set(linked_shader_modules)
                    )
                    pipeline_entry["pipeline_layout_hashes"] = sorted(
                        set(pipeline_entry["pipeline_layout_hashes"]) | set(layout_hashes)
                    )
                    if pipeline_hash in sizes:
                        pipeline_entry["size_bytes"] = sizes[pipeline_hash]
                    if pipeline_hash in connectivity:
                        pipeline_entry["connectivity"] = connectivity[pipeline_hash]

    for pipeline in pipelines.values():
        for module_hash in pipeline["linked_shader_modules"]:
            if module_hash in shader_modules:
                shader_modules[module_hash]["linked_pipelines"].append(pipeline["pipeline_hash"])
                shader_modules[module_hash]["usage_count"] += 1

    shader_module_rows = []
    for module in sorted(shader_modules.values(), key=lambda item: item["shader_module_hash"]):
        module["linked_pipelines"] = sorted(set(module["linked_pipelines"]))
        module["usage_count"] = len(module["linked_pipelines"])
        shader_module_rows.append(module)

    pipeline_rows = []
    for pipeline in sorted(pipelines.values(), key=lambda item: (item["pipeline_type"], item["pipeline_hash"])):
        size_info = pipeline.get("size_bytes", {})
        pipeline["module_count"] = len(pipeline["linked_shader_modules"])
        pipeline["linked_shader_usage_sum"] = sum(
            shader_modules.get(module_hash, {}).get("usage_count", 0)
            for module_hash in pipeline["linked_shader_modules"]
        )
        pipeline["inspection_priority_score"] = (
            size_info.get("uncompressed_size_bytes", 0)
            + size_info.get("compressed_size_bytes", 0)
            + (pipeline["module_count"] * 256)
            + (pipeline["linked_shader_usage_sum"] * 64)
        )
        pipeline_rows.append(pipeline)

    candidate_hot = []
    for pipeline in sorted(
        pipeline_rows,
        key=lambda item: item["inspection_priority_score"],
        reverse=True,
    )[: args.candidate_limit]:
        candidate_hot.append(
            {
                "session_id": pipeline["session_id"],
                "pipeline_hash": pipeline["pipeline_hash"],
                "pipeline_type": pipeline["pipeline_type"],
                "inspection_priority_score": pipeline["inspection_priority_score"],
                "linked_shader_modules": pipeline["linked_shader_modules"],
                "reasons": [
                    "large_fossilize_object_size",
                    "multiple_linked_shader_modules" if pipeline["module_count"] > 1 else "single_shader_pipeline",
                    "reused_shader_modules" if pipeline["linked_shader_usage_sum"] > 1 else "low_reuse",
                ],
                "method_notes": "This is an inspection-priority heuristic, not a runtime hotness metric.",
                "track_a_match": pipeline["track_a_match"],
            }
        )

    disassembly_reference = {
        "session_id": session_manifest["session_id"],
        "status": "placeholder_only",
        "fossilize_disasm": tool_reports["fossilize-disasm"],
        "expected_output_dirs": {
            "spirv": repo_relative(paths["track_b_spirv_dir"]),
            "isa": repo_relative(paths["track_b_isa_dir"]),
            "disassembly": repo_relative(paths["track_b_disassembly_dir"]),
        },
        "notes": [
            "The repository resolves fossilize-disasm, but `.foz` mining alone does not provide the `state.json` input needed for direct disassembly.",
            "Use this slot after exporting or reconstructing the appropriate Fossilize state for a specific session.",
        ],
    }

    outputs = {
        "pipelines_json": paths["track_b_summaries_dir"] / "pipelines_summary.json",
        "pipelines_csv": paths["track_b_summaries_dir"] / "pipelines_summary.csv",
        "shader_modules_json": paths["track_b_summaries_dir"] / "shader_modules_summary.json",
        "candidate_hot_json": paths["track_b_summaries_dir"] / "candidate_hot_pipelines.json",
        "disassembly_references_json": paths["track_b_summaries_dir"] / "disassembly_references.json",
    }

    write_json(outputs["pipelines_json"], pipeline_rows)
    write_json(outputs["shader_modules_json"], shader_module_rows)
    write_json(outputs["candidate_hot_json"], candidate_hot)
    write_json(outputs["disassembly_references_json"], disassembly_reference)
    write_csv(
        outputs["pipelines_csv"],
        [
            {
                "session_id": pipeline["session_id"],
                "pipeline_hash": pipeline["pipeline_hash"],
                "pipeline_type": pipeline["pipeline_type"],
                "module_count": pipeline["module_count"],
                "linked_shader_modules": ";".join(pipeline["linked_shader_modules"]),
                "compressed_size_bytes": pipeline.get("size_bytes", {}).get("compressed_size_bytes", 0),
                "uncompressed_size_bytes": pipeline.get("size_bytes", {}).get("uncompressed_size_bytes", 0),
                "inspection_priority_score": pipeline["inspection_priority_score"],
                "track_a_confidence": pipeline["track_a_match"]["confidence"],
            }
            for pipeline in pipeline_rows
        ],
        fieldnames=[
            "session_id",
            "pipeline_hash",
            "pipeline_type",
            "module_count",
            "linked_shader_modules",
            "compressed_size_bytes",
            "uncompressed_size_bytes",
            "inspection_priority_score",
            "track_a_confidence",
        ],
    )

    for output_name, output_path in outputs.items():
        record_artifact(
            session_root,
            track_key="track_b",
            kind=output_name,
            canonical_path=output_path,
            source_path=None,
            label=output_path.name,
            metadata={"output_type": output_name},
            provenance={"generated_by": "mine_pipelines.py"},
            generated=True,
        )

    track_manifest["status"] = "pipeline_metadata_mined"
    track_manifest["summary_outputs"] = {name: repo_relative(path) for name, path in outputs.items()}
    track_manifest["notes"].append(
        "Pipeline candidates are prioritized by Fossilize object metadata only. Runtime hotness still requires profiling."
    )
    save_track_manifest(session_root, "track_b", track_manifest)
    update_track_status(session_root, "track_b", "pipeline_metadata_mined")
    append_command_record(session_root, "track_b", ["mine_pipelines.py", "--session", args.session], fossilize_list["path"])
    print(f"Mined {len(pipeline_rows)} pipelines and {len(shader_module_rows)} shader modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

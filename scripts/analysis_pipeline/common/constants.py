"""Shared constants for the thesis analysis pipeline."""

from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = "1.0"
MANIFEST_VERSION = "1.0"

REPO_ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_ROOT = REPO_ROOT / "analysis"
GAMES_ROOT = ANALYSIS_ROOT / "games"
SCHEMAS_ROOT = ANALYSIS_ROOT / "schemas"
TEMPLATES_ROOT = ANALYSIS_ROOT / "templates"
REPORTS_ROOT = ANALYSIS_ROOT / "reports"
TOOLS_ROOT = ANALYSIS_ROOT / "tools"
LOCAL_TOOLS_ROOT = TOOLS_ROOT / "local"
WRAPPERS_ROOT = TOOLS_ROOT / "wrappers"

SESSION_DIR_NAMES = {
    "manifests": "manifests",
    "metadata": "metadata",
    "track_a": "track_a_frame_capture",
    "track_b": "track_b_pipeline_mining",
    "track_c": "track_c_correlation",
    "notes": "notes",
    "exports": "exports",
}

TRACK_MANIFEST_FILENAMES = {
    "track_a": "track_a_manifest.json",
    "track_b": "track_b_manifest.json",
    "track_c": "correlation_manifest.json",
}

TRACK_STATUS_KEYS = {
    "track_a": "track_a",
    "track_b": "track_b",
    "track_c": "track_c",
}

TOOL_CANDIDATES = {
    "renderdoccmd": [
        LOCAL_TOOLS_ROOT / "renderdoc" / "renderdoccmd",
        LOCAL_TOOLS_ROOT / "bin" / "renderdoccmd",
    ],
    "qrenderdoc": [
        LOCAL_TOOLS_ROOT / "renderdoc" / "qrenderdoc",
        LOCAL_TOOLS_ROOT / "bin" / "qrenderdoc",
    ],
    "fossilize-list": [
        REPO_ROOT / "build" / "install" / "bin" / "fossilize-list",
        REPO_ROOT / "build" / "fossilize" / "cli" / "fossilize-list",
        LOCAL_TOOLS_ROOT / "fossilize" / "fossilize-list",
        LOCAL_TOOLS_ROOT / "bin" / "fossilize-list",
    ],
    "fossilize-disasm": [
        REPO_ROOT / "build" / "install" / "bin" / "fossilize-disasm",
        REPO_ROOT / "build" / "fossilize" / "cli" / "fossilize-disasm",
        LOCAL_TOOLS_ROOT / "fossilize" / "fossilize-disasm",
        LOCAL_TOOLS_ROOT / "bin" / "fossilize-disasm",
    ],
    "fossilize-replay": [
        REPO_ROOT / "build" / "install" / "bin" / "fossilize-replay",
        REPO_ROOT / "build" / "fossilize" / "cli" / "fossilize-replay",
        LOCAL_TOOLS_ROOT / "fossilize" / "fossilize-replay",
        LOCAL_TOOLS_ROOT / "bin" / "fossilize-replay",
    ],
    "rga": [
        REPO_ROOT / "radeon_gpu_analyzer" / "build" / "util" / "linux" / "rga",
        LOCAL_TOOLS_ROOT / "rga" / "rga",
        LOCAL_TOOLS_ROOT / "bin" / "rga",
    ],
    "rgp": [
        LOCAL_TOOLS_ROOT / "rgp" / "rgp",
        LOCAL_TOOLS_ROOT / "bin" / "rgp",
    ],
    "amdllpc": [
        LOCAL_TOOLS_ROOT / "amdllpc" / "amdllpc",
        LOCAL_TOOLS_ROOT / "bin" / "amdllpc",
    ],
    "amdspv": [
        LOCAL_TOOLS_ROOT / "amdspv" / "amdspv",
        LOCAL_TOOLS_ROOT / "bin" / "amdspv",
    ],
}

FOSSILIZE_TAGS = {
    1: "sampler",
    2: "descriptorSet",
    3: "pipelineLayout",
    4: "shaderModule",
    5: "renderPass",
    6: "graphicsPipeline",
    7: "computePipeline",
    8: "applicationBlobLink",
    9: "raytracingPipeline",
}

PIPELINE_TAGS = {6: "graphicsPipeline", 7: "computePipeline", 9: "raytracingPipeline"}

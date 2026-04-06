# Thesis Analysis Workflow

This directory holds the thesis-friendly workflow for comparing RDNA3 behavior across games, scenes, pipelines, compiler variants, and optional profiling artifacts.

## Design

- `analysis/games/<game>/config/` stores per-game config and capture notes.
- `analysis/games/<game>/sessions/<session_id>/` stores all session-local evidence.
- `analysis/schemas/` documents the expected JSON shapes.
- `analysis/templates/` provides reusable config and note templates.
- `analysis/tools/` is the preferred location for repo-local tool installs and wrappers.
- `analysis/reports/` is reserved for later cross-session rollups.

## Exact Capture Order

1. Create a session with Track A session init.
2. Prepare Track A instructions for that session.
3. Launch the game with the intended graphics settings, Proton version, and capture notes.
4. Reach the named scene and stabilize the real frame.
5. Capture the frame with RenderDoc.
6. Save screenshot(s), scene notes, and any draw/frame marker exports you can obtain.
7. Preserve `.foz` files generated from the same capture window.
8. Register Track A artifacts.
9. Register Track B `.foz` artifacts.
10. Run Track B pipeline mining.
11. Register optional ISA / compiler log / RGA / profiling artifacts.
12. Run Track C correlation.
13. Export the session summary for later thesis writing.

## Standard Session Slots

Every session is created under:

`analysis/games/<game>/sessions/<game>__<scene>__<YYYYMMDD_HHMMSS>/`

Minimum standardized slots:

- `manifests/session_manifest.json`
- `manifests/artifact_registry.json`
- `manifests/track_a_manifest.json`
- `manifests/track_b_manifest.json`
- `manifests/correlation_manifest.json`
- `metadata/capture_environment.json`
- `notes/operator_notes.md`
- `notes/scene_description.md`
- `notes/hypotheses.md`
- `track_a_frame_capture/renderdoc/`
- `track_a_frame_capture/screenshots/`
- `track_a_frame_capture/frame_markers/`
- `track_a_frame_capture/logs/`
- `track_b_pipeline_mining/inputs/foz/`
- `track_b_pipeline_mining/summaries/`
- `track_b_pipeline_mining/extracted/`
- `track_c_correlation/inputs/`
- `track_c_correlation/outputs/`
- `exports/thesis_session_summary.md`

## What To Save Per Session

Track A:

- RenderDoc `.rdc` capture files
- Scene screenshots
- Manual notes
- Optional draw summaries
- Optional frame marker exports
- Optional capture logs

Track B:

- One or more `.foz` files from the same scene/session context
- Mined `pipelines_summary.json`
- Mined `pipelines_summary.csv`
- Mined `shader_modules_summary.json`
- Mined `candidate_hot_pipelines.json`
- Optional SPIR-V / ISA references when later available

Track C:

- ISA dumps
- Compiler logs
- RGA reports
- RGP / SQTT / other profiling artifacts
- Manual annotation file linking hashes, draw calls, or captures
- `correlation_summary.json`
- `correlation_summary.md`
- `pipeline_correlation_table.csv`
- `unresolved_matches.json`

## Correlation Strategy

The pipeline explicitly models uncertain correlation. Matching basis can include:

- shared `session_id`
- shared game / scene slug
- capture timestamp window
- Fossilize pipeline hashes
- shader module hashes
- filenames and provenance
- manual annotation file

Confidence labels:

- `exact`: exact pipeline hash match
- `strong`: linked shader module hash or explicit annotation match
- `weak`: only session/scene linkage exists
- `unresolved`: insufficient evidence

## Tool Resolution Policy

Each script prefers:

1. `analysis/tools/local/`
2. vendored or locally built repo assets such as `build/install/bin/` and `radeon_gpu_analyzer/`
3. system `PATH`

Every script prints which tool path it resolved. Missing tools are reported honestly.

## Script Entry Points

Create a session:

```bash
python3 -m scripts.analysis_pipeline.init_session \
  --game remnant2 \
  --scene ward13_idle \
  --settings-profile ultra_1440p \
  --comparison-cohort high_gain_group \
  --proton-version proton_experimental \
  --mesa-build-info local_mesa_build \
  --compiler-variant-tag baseline
```

Prepare Track A:

```bash
python3 -m scripts.analysis_pipeline.track_a.prepare_capture \
  --session remnant2__ward13_idle__20260405_120000
```

Register Track A manual artifacts:

```bash
python3 -m scripts.analysis_pipeline.track_a.register_capture \
  --session remnant2__ward13_idle__20260405_120000 \
  --rdc /path/to/frame.rdc \
  --screenshot /path/to/frame.png \
  --note-file /path/to/capture_notes.md
```

Register `.foz` for Track B:

```bash
python3 -m scripts.analysis_pipeline.track_b.register_foz \
  --session remnant2__ward13_idle__20260405_120000 \
  --foz /path/to/steamapp_pipeline_cache.foz
```

Mine Track B outputs:

```bash
python3 -m scripts.analysis_pipeline.track_b.mine_pipelines \
  --session remnant2__ward13_idle__20260405_120000
```

Register optional Track C inputs:

```bash
python3 -m scripts.analysis_pipeline.track_c.register_optional_artifacts \
  --session remnant2__ward13_idle__20260405_120000 \
  --compiler-log isa_dumps/raw_dump.log \
  --isa-file isa_dumps/raw_dump.log \
  --manual-annotation /path/to/manual_annotation.json
```

Run correlation:

```bash
python3 -m scripts.analysis_pipeline.track_c.correlate_session \
  --session remnant2__ward13_idle__20260405_120000 \
  --run-legacy-extract
```

## Honest Limits

- RenderDoc capture is prepared and registered here, not fully automated.
- `.foz` mining does not recreate full scene state.
- Fossilize object connectivity is available immediately; shader stage mapping may still require extra exports or manual annotation.
- Candidate hot pipelines are inspection-priority heuristics, not measured runtime hotspots.

# Track A README

Track A is the real-frame capture track. Its job is to preserve the actual scene context that was visible in-game at the moment of analysis.

## Purpose

Use Track A to capture and register:

- RenderDoc `.rdc` captures
- scene screenshots
- draw summaries if available
- frame marker exports if available
- operator notes
- capture environment metadata

Track A is the anchor for the rest of the workflow. It defines the real scene that Track B and Track C should relate to.

## Requirements

Required:

- Linux host
- game configured under `analysis/games/<game>/config/game_config.json`
- a valid session created with `init_session.py`
- manual access to the game under Steam + Proton or native Linux execution

Strongly recommended:

- RenderDoc installed locally or on system `PATH`
- a stable scene label and graphics settings profile
- notes about Proton version, Mesa/RADV build, and capture conditions

Optional:

- draw call exports
- frame marker exports
- capture-side logs

## What Track A Is Not

- It does not automate in-game navigation.
- It does not guarantee exact pipeline identification on its own.
- It does not replace `.foz` mining.

## Correct Order

1. Create a session.
2. Prepare Track A instructions.
3. Launch the game with the intended graphics profile and runtime notes.
4. Reach the named scene.
5. Trigger a RenderDoc capture manually.
6. Save screenshot(s) and operator notes.
7. Register those artifacts into the session.

## Commands

Create a session:

```bash
python3 -m scripts.analysis_pipeline.init_session \
  --game remnant2 \
  --scene ward13_idle \
  --settings-profile ultra_1440p \
  --comparison-cohort high_gain_group
```

Prepare the capture session:

```bash
python3 -m scripts.analysis_pipeline.track_a.prepare_capture \
  --session remnant2__ward13_idle__20260405_120000
```

Register manual capture artifacts:

```bash
python3 -m scripts.analysis_pipeline.track_a.register_capture \
  --session remnant2__ward13_idle__20260405_120000 \
  --rdc /path/to/frame.rdc \
  --screenshot /path/to/frame.png \
  --note-file /path/to/capture_notes.md \
  --draw-summary /path/to/draw_summary.json \
  --frame-marker-file /path/to/frame_markers.txt
```

## Inputs

Expected inputs:

- game slug
- scene slug
- graphics settings profile
- comparison cohort
- optional Proton / Mesa / RADV / compiler metadata

Manual artifacts after capture:

- `.rdc`
- screenshots
- notes
- logs
- exported summaries if available

## Outputs

Track A writes into the session:

- `track_a_frame_capture/capture_instructions.md`
- `track_a_frame_capture/renderdoc/`
- `track_a_frame_capture/screenshots/`
- `track_a_frame_capture/frame_markers/`
- `track_a_frame_capture/logs/`
- `manifests/track_a_manifest.json`
- `manifests/artifact_registry.json`
- `metadata/capture_environment.json`

## Correct Usage Rules

- Always keep Track A tied to a single `session_id`.
- Capture the same scene that will later be associated with the `.foz` files.
- Record enough scene detail that the scene can be revisited later.
- If RenderDoc is missing, do not fake capture completion. Keep the session in a prepared or partial state.

## Tool Expectations

Primary tool:

- `renderdoccmd`
- `qrenderdoc`

Fallback reality:

- If RenderDoc is not available locally, the pipeline still prepares canonical storage and instructions.
- Tool resolution is recorded in the session metadata and must remain honest.

## Common Failure Modes

- Capturing the wrong scene relative to the `.foz` collection window
- missing screenshots or notes, which weakens future correlation
- failing to record Proton or Mesa build details
- treating Track A as optional when you want scene-grounded analysis

## Minimum Good Track A Session

At minimum, a useful Track A session should contain:

- one session manifest
- one scene description
- one operator notes file
- one screenshot
- one RenderDoc capture or a clearly documented reason it is missing

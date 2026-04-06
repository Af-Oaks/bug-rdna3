# RDNA3 Thesis Workflow

This repository investigates which workload, pipeline, shader, compiler, and runtime characteristics correlate with high gains versus low gains on RDNA3 relative to RDNA2-era expectations. The focus is Linux, Proton, Vulkan, RADV, and ACO behavior.

## Main Areas

- `analysis/` is the thesis-facing workflow area for per-game, per-scene sessions.
- `scripts/analysis_pipeline/` contains the three-track orchestration scripts.
- `custom_mesa_layer/`, `scripts/build_custom_aco.sh`, `scripts/test_fossilize.sh`, and `src/` remain the existing compiler experiment area.
- `build/`, `lib/`, `radeon_gpu_analyzer/`, and vendored tool trees remain useful as local tool sources.

## Three Tracks

- Track A: real-frame capture with RenderDoc as the primary path
- Track B: `.foz` mining for pipeline and shader objects from the same scene/session context
- Track C: correlation across frame capture, pipeline mining, compiler artifacts, ISA outputs, and optional profiling artifacts

## Quick Start

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

What this does:

- creates the canonical session folder
- creates the manifests and artifact registry
- creates note and metadata files for that exact game + scene + run

When to run it:

- run this before launching the game for the capture attempt
- it is the administrative start of a new scene analysis session
- it does not launch the game and it does not capture anything by itself

Prepare Track A:

```bash
python3 -m scripts.analysis_pipeline.track_a.prepare_capture \
  --session remnant2__ward13_idle__20260405_120000
```

What this does:

- writes the capture instructions into the session folder
- records expected RenderDoc artifact locations
- resolves and records which RenderDoc tools are available locally

When to run it:

- run this before launching the game, or before starting the actual capture attempt
- its purpose is to prepare the session so you know exactly what to save once the scene is ready
- it does not capture a frame by itself

What happens next:

- after this step, launch the game
- reach the exact named scene
- stabilize the scene you want to analyze
- only then perform the real RenderDoc capture manually
- after capturing, register the `.rdc`, screenshot, and any notes with `track_a.register_capture`

Register `.foz` and mine Track B:

```bash
python3 -m scripts.analysis_pipeline.track_b.register_foz \
  --session remnant2__ward13_idle__20260405_120000 \
  --foz src/shaders/remnant2/steamapp_pipeline_cache.foz

python3 -m scripts.analysis_pipeline.track_b.mine_pipelines \
  --session remnant2__ward13_idle__20260405_120000
```

What this means in practice:

- do not mine `.foz` before you have the right `.foz` file from the same capture window or same scene/session context
- the correct order is usually:
  1. create session
  2. prepare Track A
  3. launch the game
  4. reach the scene
  5. capture the real frame with RenderDoc
  6. preserve or copy the `.foz` generated from that same run/session window
  7. register the `.foz`
  8. mine Track B

What `register_foz` does:

- copies the selected `.foz` into the canonical session folder
- records provenance, checksums, and linkage to the session

What `mine_pipelines` does:

- reads the registered `.foz`
- extracts pipeline and shader object metadata through Fossilize
- writes normalized JSON and CSV summaries for later correlation

Important:

- `.foz` mining is not something you normally do before launching the game
- first you need the `.foz` produced by the real run you care about
- Track B should be tied to the same scene/session context as Track A, not an unrelated cache dump

Run correlation:

```bash
python3 -m scripts.analysis_pipeline.track_c.register_optional_artifacts \
  --session remnant2__ward13_idle__20260405_120000 \
  --compiler-log isa_dumps/raw_dump.log

python3 -m scripts.analysis_pipeline.track_c.correlate_session \
  --session remnant2__ward13_idle__20260405_120000 \
  --run-legacy-extract
```

When to run this:

- run correlation only after Track B outputs exist
- ideally after Track A artifacts and any optional ISA/compiler/profiling artifacts have also been registered
- if you run Track C too early, the result will correctly stay weak or unresolved

## Practical Order

Use the workflow in this order:

1. Create session before launching the game.
2. Prepare Track A before the capture attempt.
3. Launch the game.
4. Reach the target scene and make it stable enough to reproduce.
5. Capture the real frame manually with RenderDoc.
6. Save screenshot(s) and notes immediately.
7. Preserve the `.foz` files generated from that same run or capture window.
8. Register Track A artifacts.
9. Register the `.foz` files for Track B.
10. Run Track B mining.
11. Register optional ISA, compiler, RGA, or profiling artifacts.
12. Run Track C correlation.

## How To Capture RenderDoc Correctly

Goal:

- capture the real frame from the exact scene you want to analyze

Recommended order:

1. Create the session first.
2. Run `track_a.prepare_capture` before launching the game.
3. Launch the game after the session is already prepared.
4. Reach the target scene.
5. Wait until the scene is in the exact state you want to study.
6. Trigger the RenderDoc capture manually at that moment.
7. Save at least one screenshot immediately after or around the capture.
8. Write operator notes about camera position, motion state, effects, NPC state, and anything transient.
9. Register the `.rdc` and screenshot into the session with `track_a.register_capture`.

Important guidance:

- Do not capture too early, before the scene is ready.
- Do not create the session after the capture; create it first so the run is already organized.
- Treat the RenderDoc capture as the real-scene anchor for later correlation.
- If you export draw summaries or frame markers from RenderDoc, register those too because they can help Track C later.

What to save from RenderDoc:

- `.rdc` capture file
- one or more screenshots
- optional draw summaries
- optional frame markers
- short notes describing what was on screen

## How To Capture `.foz` Correctly

Goal:

- preserve the Fossilize cache data generated from the same run and same scene/session context as the RenderDoc capture

What matters:

- the `.foz` should come from the same gameplay run or capture window as Track A
- it does not have to be copied before launching the game
- it usually needs to be preserved after the game has already run the target scene

Recommended order:

1. Prepare the session before launching the game.
2. Launch the game.
3. Reach the same target scene used for the RenderDoc capture.
4. Let the scene render long enough for the relevant pipelines and shaders to be exercised.
5. Perform the RenderDoc capture while the scene is ready.
6. After that run, preserve the `.foz` file or files produced by that same game session.
7. Copy or register those `.foz` files into the session with `track_b.register_foz`.
8. Only after registration, run `track_b.mine_pipelines`.

Practical rule:

- the `.foz` is not something you usually "capture" with a button the way you do with RenderDoc
- instead, you preserve the Fossilize cache files generated by the game run you care about

What to save for `.foz`:

- the relevant `.foz` file or files from the game shader cache location
- enough notes to explain that they came from the same run/session window as the RenderDoc capture

How to keep `.foz` and RenderDoc aligned:

- use the same `session_id`
- use the same game slug and scene slug
- collect both from the same run whenever possible
- avoid mixing `.foz` from older unrelated play sessions
- if exact linkage is uncertain, say so explicitly in notes or manual annotations

## Minimal Real Capture Recipe

If you want the shortest correct real-world procedure:

1. Create session.
2. Prepare Track A.
3. Launch game.
4. Reach scene.
5. Capture frame with RenderDoc.
6. Save screenshot and notes.
7. Preserve the `.foz` generated from that same run.
8. Register Track A artifacts.
9. Register `.foz`.
10. Mine Track B.

## What The Scripts Do Not Do

- They do not launch the game.
- They do not navigate to the scene for you.
- They do not automatically trigger the RenderDoc capture.
- They do not guarantee exact pipeline matching without enough evidence.
- They do not make `.foz` equal to full scene replay.

## Notes

- Tool resolution prefers repo-local tools first, vendored/local builds second, and system tools last.
- `extract.py` is preserved and wrapped as an optional legacy helper; it is not the primary workflow.
- The detailed capture order, session slots, and manifest expectations are documented in [`analysis/README.md`](/home/methos/Documents/faculdade/TCC_bug_amd/analysis/README.md).
- Fast domain context is documented in [`DOMAIN.md`](/home/methos/Documents/faculdade/TCC_bug_amd/DOMAIN.md).


## Example

Minimal two-script workflow with the current repo:

1. Create the session once. This creates the canonical folder tree where you will manually drop the artifacts from RenderDoc and the game `.foz`.

```bash
python3 -m scripts.analysis_pipeline.init_session \
  --game remnant2 \
  --scene ward13_idle \
  --settings-profile ultra_1440p \
  --comparison-cohort high_gain_group \
  --proton-version proton_experimental \
  --mesa-build-info local_mesa_build \
  --compiler-variant-tag baseline \
  --session-timestamp 20260405_120000
```

2. After that command, use this session folder:

```text
analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/
```

3. Launch the game, reach the target scene, capture the frame with RenderDoc, and preserve the `.foz` generated from that same run.

4. Manually place the files inside the session folders:

```text
analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/
├── track_a_frame_capture/renderdoc/
│   └── frame.rdc
├── track_a_frame_capture/screenshots/
│   └── frame.png
├── track_a_frame_capture/frame_markers/
│   └── draw_summary.json              # optional
├── track_a_frame_capture/logs/
│   └── renderdoc_log.txt              # optional
├── track_b_pipeline_mining/inputs/foz/
│   └── steamapp_pipeline_cache.foz
└── track_c_correlation/inputs/
    ├── compiler_logs/
    │   └── raw_dump.log               # optional
    ├── isa_dumps/
    │   └── raw_dump.log               # optional
    ├── rga_reports/                   # optional
    ├── profiling/                     # optional
    └── manual_annotations/            # optional
```

5. Run the session pipeline with one command:

```bash
python3 -m scripts.analysis_pipeline.run_session \
  --session remnant2__ward13_idle__20260405_120000 \
  --run-legacy-extract
```

What this second script does:

- registers the files already placed inside the session folders
- treats the session folders as the source of truth
- runs Track B mining from the `.foz` found in `track_b_pipeline_mining/inputs/foz/`
- runs Track C correlation from the artifacts already present in the session
- writes summaries, CSVs, JSON outputs, and the thesis session export

Practical meaning:

- first script = create the session skeleton
- manual step = capture and place `.rdc`, screenshot, `.foz`, and optional artifacts
- second script = register everything in place and execute the rest of the workflow

If `run_session` does not find a `.foz` inside the session folder, it stops and tells you to place the `.foz` there first.

## Track Docs

- Track A requirements and correct usage: [`scripts/analysis_pipeline/track_a/README.md`](/home/methos/Documents/faculdade/TCC_bug_amd/scripts/analysis_pipeline/track_a/README.md)
- Track B requirements and correct usage: [`scripts/analysis_pipeline/track_b/README.md`](/home/methos/Documents/faculdade/TCC_bug_amd/scripts/analysis_pipeline/track_b/README.md)
- Track C requirements and correct usage: [`scripts/analysis_pipeline/track_c/README.md`](/home/methos/Documents/faculdade/TCC_bug_amd/scripts/analysis_pipeline/track_c/README.md)

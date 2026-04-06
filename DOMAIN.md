# Domain Summary

This repository is a thesis workspace for investigating which workload, pipeline, shader, compiler, and runtime characteristics correlate with high gains versus low gains on RDNA3 relative to RDNA2-era expectations.

## Core Framing

- Do not frame this project as proving an architectural flaw.
- The correct framing is:
  investigate and measure which workload, pipeline, shader, compiler, and runtime characteristics correlate with high gains versus low gains on RDNA3.
- The comparison target is usually across games, scenes, and later compiler variants such as baseline versus modified ACO.
- The main software stack is Linux + Steam + Proton + Vulkan + Mesa/RADV + ACO.

## Repo Intent

The repo has two parallel purposes:

1. Thesis analysis workflow
   - Per-game and per-scene session management
   - Real frame capture
   - `.foz` pipeline mining
   - Cross-artifact correlation

2. Compiler experiment workspace
   - `custom_mesa_layer/`
   - `scripts/build_custom_aco.sh`
   - `scripts/test_fossilize.sh`
   - `src/`

The thesis-facing workflow is centered on:

- `analysis/`
- `scripts/analysis_pipeline/`

## Three Tracks

### Track A

Purpose:

- Capture the real frame and scene context actually seen in the game.

Primary tool:

- RenderDoc

What Track A is for:

- `.rdc` capture files
- scene screenshots
- frame marker exports if available
- draw summaries if available
- operator notes
- environment and capture metadata

What Track A is not:

- It is not full automation of in-game navigation.
- It is not a guarantee of exact pipeline identification by itself.

Correct use:

1. Create a session.
2. Prepare Track A instructions.
3. Launch the game with the intended graphics profile, Proton version, and notes.
4. Reach the named scene.
5. Capture with RenderDoc.
6. Save screenshots and notes from the same scene.
7. Register those artifacts into the session.

### Track B

Purpose:

- Mine pipeline and shader object information from Fossilize `.foz` files generated from the same scene/session context as Track A.

Primary tools:

- `fossilize-list`
- optional `fossilize-disasm`

What Track B is for:

- shader module hashes
- pipeline hashes
- pipeline connectivity metadata
- normalized summaries in JSON and CSV
- candidate inspection pipelines
- placeholders for later SPIR-V / ISA references

What Track B is not:

- It is not full scene reconstruction.
- It is not a substitute for real frame capture.
- It is not proof that a mined pipeline was visible in the captured frame unless the linkage is established.

Correct use:

1. Preserve `.foz` files from the same capture window as Track A.
2. Register the `.foz` files in the same session.
3. Run the mining script.
4. Use the resulting pipeline and shader summaries as candidates for later correlation.

### Track C

Purpose:

- Correlate Track A scene/frame artifacts with Track B pipeline mining and optional compiler or profiling evidence.

Primary inputs:

- Track A manifests and artifacts
- Track B outputs
- optional ISA dumps
- optional compiler logs
- optional RGA outputs
- optional profiling artifacts such as RGP/SQTT
- optional manual annotation files

What Track C is for:

- confidence-scored correlation
- unresolved match tracking
- pipeline correlation tables
- thesis-ready session summaries
- future baseline versus modified ACO comparison slots

Correct use:

1. Run Track B first.
2. Import optional artifacts from the same capture window.
3. Add manual annotations if exact matching is not available.
4. Run correlation.
5. Treat `exact`, `strong`, `weak`, and `unresolved` as meaningful states, not cosmetic labels.

## Session Model

Everything revolves around a session:

- one game
- one scene label
- one run timestamp
- one graphics settings profile
- one Proton version
- one Mesa/RADV build description if known
- one compiler or ACO variant tag if known
- one comparison cohort

Canonical session id:

- `<game_slug>__<scene_slug>__<YYYYMMDD_HHMMSS>`

Every artifact in Tracks A, B, and C must link back to the same `session_id`.

## Setup Levels

Think about setup in levels.

### Level 0: Repo Understanding

Read these first:

- `GEMINI.md`
- `AGENTS.md`
- `DOMAIN.md`
- `analysis/README.md`

This gives the framing, workflow, and non-goals.

### Level 1: Per-Game Setup

Per-game config lives in:

- `analysis/games/<game>/config/game_config.json`

This should define:

- game slug
- display name
- Steam app id if known
- executable notes
- Proton notes
- known scene labels
- recommended launch options
- capture notes
- expected `.foz` location patterns

Before using a game seriously, update its config.

### Level 2: Session Setup

Create a session with:

```bash
python3 -m scripts.analysis_pipeline.init_session \
  --game <game_slug> \
  --scene <scene_slug> \
  --settings-profile <profile> \
  --comparison-cohort <high_gain_group|low_gain_group|other>
```

This creates:

- session manifests
- artifact registry
- note files
- metadata files
- canonical Track A/B/C directories

### Level 3: Track A Preparation

Prepare the session:

```bash
python3 -m scripts.analysis_pipeline.track_a.prepare_capture \
  --session <session_id>
```

This writes:

- capture instructions
- expected artifact slots
- tool resolution results

### Level 4: Track A Registration

After manual capture:

```bash
python3 -m scripts.analysis_pipeline.track_a.register_capture \
  --session <session_id> \
  --rdc /path/to/frame.rdc \
  --screenshot /path/to/frame.png
```

Add any extra notes, logs, draw summaries, or marker exports at this point.

### Level 5: Track B Registration and Mining

Register `.foz`:

```bash
python3 -m scripts.analysis_pipeline.track_b.register_foz \
  --session <session_id> \
  --foz /path/to/cache.foz
```

Mine outputs:

```bash
python3 -m scripts.analysis_pipeline.track_b.mine_pipelines \
  --session <session_id>
```

### Level 6: Track C Registration and Correlation

Register optional evidence:

```bash
python3 -m scripts.analysis_pipeline.track_c.register_optional_artifacts \
  --session <session_id> \
  --isa-file /path/to/isa.log \
  --compiler-log /path/to/compiler.log \
  --manual-annotation /path/to/manual_annotation.json
```

Run correlation:

```bash
python3 -m scripts.analysis_pipeline.track_c.correlate_session \
  --session <session_id> \
  --run-legacy-extract
```

## Tool Policy

Every script should prefer:

1. local repo-managed tools under `analysis/tools/local/`
2. vendored or locally built tools already present in the repo
3. system `PATH`

Current important tools:

- RenderDoc
  - `renderdoccmd`
  - `qrenderdoc`
- Fossilize
  - `fossilize-list`
  - `fossilize-disasm`
  - `fossilize-replay`
- RGA
  - `rga`
- optional profiling
  - `rgp`

Current local/vendored priorities in this repo:

- Fossilize binaries are available under `build/install/bin/`
- RGA may be available under `radeon_gpu_analyzer/build/util/linux/`
- RenderDoc is not currently vendored in the repo and may need local or system installation

Important rule:

- Scripts must print which tool path they resolved.
- Missing tools must be reported honestly.

## Output Philosophy

Machine-readable outputs:

- JSON
- CSV

Human-readable outputs:

- Markdown

Why:

- easy to diff
- easy to inspect
- easy to use later in thesis writing

## Confidence Model

The workflow must never fake certainty.

Confidence levels:

- `exact`
  - exact pipeline hash match
- `strong`
  - linked shader hash or explicit manual annotation
- `weak`
  - same session and scene context, but no exact identifier match
- `unresolved`
  - not enough evidence

If exact matching is unavailable, keep the unresolved state explicit.

## Future Comparison Goal

The long-term purpose is to compare:

- high-gain scenes versus low-gain scenes
- baseline compiler versus modified ACO
- possible differences in occupancy
- register pressure
- scheduling quality
- instruction mix
- runtime behavior

The workflow should always preserve enough metadata to support that later A/B comparison.

## Non-Goals

- Do not make `gfxreconstruct` the main workflow.
- Do not claim `.foz` reconstructs the real visual scene.
- Do not force exact pipeline matching where only heuristics exist.
- Do not silently install tools.
- Do not hide assumptions about capture timing, provenance, or uncertainty.

## Fast Prompt Context

If a future prompt needs quick context, the minimum useful summary is:

- This repo studies RDNA3 gain variability across games and scenes, not architectural blame.
- Track A is RenderDoc-based real frame capture.
- Track B is Fossilize `.foz` mining from the same capture context.
- Track C correlates Track A, Track B, and optional ISA/compiler/profiling evidence.
- Every artifact must be session-scoped and traceable by manifest and checksum.
- Use local tools first, vendored tools second, system tools last.
- Be explicit about uncertainty and preserve future baseline versus modified ACO comparison paths.

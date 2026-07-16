# Track B README

Track B is the pipeline mining track. Its job is to extract pipeline and shader object information from Fossilize `.foz` files generated from the same scene/session context as Track A.

## Purpose

Use Track B to produce:

- shader module inventories
- pipeline inventories
- connectivity between pipelines and shader modules
- normalized JSON and CSV summaries
- candidate inspection pipelines
- placeholders for later SPIR-V / ISA / disassembly linkage

Track B is the structured object-mining layer. It is not the real scene itself.

## Requirements

Required:

- a valid session created with `scripts.analysis_pipeline.init_session`
- one or more `.foz` files from the same capture window as Track A
- working `fossilize-list`

Preferred:

- local Fossilize binaries under `build/install/bin/`
- Track A already prepared or completed
- per-game config updated with expected `.foz` paths

Optional:

- `fossilize-disasm`
- later exported `state.json` inputs for disassembly workflows

## What Track B Is Not

- It is not a full scene replay workflow.
- It is not visual reconstruction.
- It is not proof that a given mined pipeline was used in the captured frame.

## Correct Order

1. Finish or at least prepare Track A.
2. Preserve `.foz` files from the same session window.
3. Register the `.foz` file(s) into the session.
4. Run pipeline mining.
5. Use the outputs as candidates for Track C correlation.

## Commands

Register `.foz` files:

```bash
python3 -m scripts.analysis_pipeline.track_b.register_foz \
  --session remnant2__ward13_idle__20260405_120000 \
  --foz /path/to/steamapp_pipeline_cache.foz
```

Mine normalized outputs:

```bash
python3 -m scripts.analysis_pipeline.track_b.mine_pipelines \
  --session remnant2__ward13_idle__20260405_120000 \
  --candidate-limit 20
```

## Inputs

Expected inputs:

- registered `.foz` files inside the session
- Fossilize CLI access through the local-first tool resolver

The mining step currently uses:

- object listing
- object size metadata
- object connectivity metadata

## Outputs

Track B writes into:

- `track_b_pipeline_mining/inputs/foz/`
- `track_b_pipeline_mining/summaries/pipelines_summary.json`
- `track_b_pipeline_mining/summaries/pipelines_summary.csv`
- `track_b_pipeline_mining/summaries/shader_modules_summary.json`
- `track_b_pipeline_mining/summaries/candidate_hot_pipelines.json`
- `track_b_pipeline_mining/summaries/disassembly_references.json`
- `manifests/track_b_manifest.json`
- `manifests/artifact_registry.json`

## Correct Usage Rules

- Use `.foz` files from the same scene/session context as Track A.
- Preserve provenance. Do not move anonymous cache files around without registering them.
- Treat candidate hot pipelines as inspection heuristics, not runtime hotspot proof.
- Keep unresolved stage mapping explicit unless you have additional evidence.

## Tool Expectations

Primary tools:

- `fossilize-list`
- optional `fossilize-disasm`

Current repo preference:

1. `analysis/tools/local/`
2. `build/install/bin/fossilize-*`
3. system `PATH`

## Common Failure Modes

- using `.foz` files from a different session window than Track A
- assuming `.foz` implies exact scene visibility
- assuming object size or reuse equals performance hotspot
- failing to register the `.foz` files into the canonical session folder

## Minimum Good Track B Session

At minimum, a useful Track B session should contain:

- one registered `.foz`
- one `pipelines_summary.json`
- one `shader_modules_summary.json`
- one candidate pipeline file
- provenance in the artifact registry

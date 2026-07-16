# Track C README

Track C is the correlation track. Its job is to relate the scene-grounded evidence from Track A to the object-mining outputs from Track B and to any optional compiler, ISA, RGA, or profiling artifacts.

## Purpose

Use Track C to produce:

- confidence-scored pipeline correlation
- unresolved match tracking
- thesis-ready summaries
- per-session correlation CSV and JSON outputs
- future baseline versus modified ACO comparison slots

Track C is where the workflow becomes thesis evidence instead of a collection of disconnected files.

## Requirements

Required:

- a valid session
- Track B already mined
- Track B outputs present in the session

Strongly recommended:

- Track A capture artifacts already registered
- at least one optional artifact such as compiler logs, ISA dumps, or manual annotation

Optional:

- ISA dumps
- RGA reports
- RGP or SQTT outputs
- compiler logs
- manual annotation files
- legacy `extract.py` wrapper run for log enrichment

## What Track C Is Not

- It is not guaranteed exact matching by default.
- It is not allowed to pretend heuristic matches are exact.
- It is not a substitute for collecting better evidence when confidence remains weak or unresolved.

## Correct Order

1. Ensure Track B outputs exist.
2. Register optional artifacts from the same capture window.
3. Add manual annotations if exact hash linkage is available outside the automated pipeline.
4. Run correlation.
5. Review `exact`, `strong`, `weak`, and `unresolved` results honestly.

## Commands

Register optional artifacts:

```bash
python3 -m scripts.analysis_pipeline.track_c.register_optional_artifacts \
  --session remnant2__ward13_idle__20260405_120000 \
  --isa-file /path/to/isa.log \
  --compiler-log /path/to/compiler.log \
  --rga-report /path/to/report.csv \
  --profiling-file /path/to/profile.rgp \
  --manual-annotation /path/to/manual_annotation.json
```

Run correlation:

```bash
python3 -m scripts.analysis_pipeline.track_c.correlate_session \
  --session remnant2__ward13_idle__20260405_120000 \
  --run-legacy-extract
```

## Inputs

Track C consumes:

- `manifests/session_manifest.json`
- Track A artifacts and manifest
- Track B summaries
- optional ISA dumps
- optional compiler logs
- optional RGA reports
- optional profiling artifacts
- optional manual annotation files

## Outputs

Track C writes:

- `track_c_correlation/outputs/correlation_summary.json`
- `track_c_correlation/outputs/correlation_summary.md`
- `track_c_correlation/outputs/pipeline_correlation_table.csv`
- `track_c_correlation/outputs/unresolved_matches.json`
- optional `*_legacy_extract.json`
- `exports/thesis_session_summary.md`
- updated `manifests/correlation_manifest.json`
- updated `manifests/artifact_registry.json`

## Confidence Rules

Use the confidence labels correctly:

- `exact`
  - exact pipeline hash match
- `strong`
  - linked shader module hash or explicit manual annotation
- `weak`
  - same scene/session context but no exact identifier match
- `unresolved`
  - insufficient evidence

If confidence is unresolved, that is a correct result, not a failure to hide.

## Tool Expectations

Optional tools:

- `rga`
- `rgp`

Legacy enrichment:

- root `extract.py` can be wrapped to sample shader-related ISA/compiler log information

The workflow must always report missing tools honestly.

## Correct Usage Rules

- Register only artifacts from the same scene/session window.
- Preserve manual annotations when exact linkage is discovered outside automation.
- Use Track C outputs to plan better follow-up captures, not just to archive files.
- Keep baseline and modified ACO tags filled in when doing compiler comparison work.

## Common Failure Modes

- correlating artifacts from different sessions
- assuming exact linkage where only shared context exists
- forgetting to import Track A capture outputs before correlation
- failing to distinguish runtime evidence from offline compiler evidence

## Minimum Good Track C Session

At minimum, a useful Track C session should contain:

- Track B summaries
- at least one optional artifact or manual annotation
- `correlation_summary.json`
- `pipeline_correlation_table.csv`
- explicit unresolved matches when exact linkage is not available

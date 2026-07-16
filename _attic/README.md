# _attic — frozen legacy code (reference only)

Nothing in this directory is executed by the current workflow. It is preserved because the
new `tcc` package ports concepts and formulas from it, and the thesis may cite the original
prototypes. Do not import from here at runtime.

## Contents

- `analysis_pipeline/` — the original Track A/B/C session pipeline
  (`scripts/analysis_pipeline/`). The session/manifest/artifact-registry concepts and the
  confidence model (`exact/strong/weak/unresolved`) were ported into `src/tcc/session.py`
  and `src/tcc/schemas/`.
- `analysis/` — the old thesis-facing tree (schemas, templates, track READMEs). The JSON
  schemas were the reference for `src/tcc/schemas/*.schema.json`.
- `prototypes/extract.py` — two-pass streaming parser that mined 60 shaders out of the
  2.1GB `RADV_DEBUG=shaders` dump (now `data/archive/raw_dump.log`). Superseded by the
  stats-first flow (`fossilize-replay --enable-pipeline-stats` + targeted
  `fossilize-disasm`).
- `prototypes/triage.py` — pandas per-shader metrics. The `stall_ratio` and `vopd_ratio`
  formulas were ported verbatim into `src/tcc/isa.py` (names appear in the thesis).
- `prototypes/hazards.py` — networkx RAW-dependency DAG → theoretical stall cycles.
  Ported into `src/tcc/hazards.py`.
- `shell/gpu_test_runner.sh` — ICD-swap + RADV_DEBUG env conventions, reused by
  `src/tcc/config.py::profile_env`.
- `shell/test_fossilize.sh` — the GLSL → SPIR-V → foz → 3-compiler ISA diff loop,
  reborn as `tcc lab`.

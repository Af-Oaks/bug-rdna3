# `core/schemas/` — the shape of files that outlive a session

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `src/core/schemas/` updates this file
> in the same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this folder exists

Three JSON files here describe the artifacts that have to still make sense
months after the run that produced them. A session directory from June must be
readable by code written in September without anyone guessing what a column
meant. That is what these schemas are for: they are the contract between past
runs and future analysis.

They are shipped inside the installed package (`pyproject.toml` declares them as
`package-data`), so validation works from an installed `tcc`, not only from a
source checkout.

## The three

### `session_manifest.schema.json` — **enforced**

What a session *is*: id, game, scene, creation time, status (`open`/`closed`),
the profiles it used, the tool resolution it saw, and the append-only step log.
`schema_version` is pinned to `const: 2`, so a manifest from an older layout
fails loudly instead of half-loading.

`session.save()` validates against this on every write.

### `artifact_registry.schema.json` — **enforced**

Every file a session produced: path, sha256, kind, producer, timestamp, size,
and `confidence` constrained to `exact | strong | weak | unresolved`. That
enum is the honesty mechanism — the repo rule is that heuristic linkage is
labelled and never implied as exact, and this is where that rule is mechanical
rather than aspirational.

`session.save()` validates against this on every write.

### `stats_table.schema.json` — **documentation only**

The tidy row schema that `analysis/stats.py` produces from
`fossilize-replay --enable-pipeline-stats`. Its description carries real
history: field names were fixed against an actual vkd3d-proton Remnant II run on
the RX 7800 XT, and it records that the column is `spilled_vgprs` (not `spills`)
because `mine.py`'s offender score depends on that exact name.

Nothing validates against it. It is a written record of intent.

## Ground rules a future change must not break

- A schema change to `session_manifest` bumps `SCHEMA_VERSION` in
  `core/session.py` *and* the `const` in the schema. They are one decision in
  two files.
- New optional fields are additive. Existing sessions on disk must keep
  validating, because they are the evidence base and cannot be re-run.
- If you add a schema, decide at the same moment whether it is enforced or
  descriptive, and say so here. One of the three is descriptive and it is not
  obvious from looking at it. A fourth, `armed_profile.schema.json`, was deleted
  2026-08-03: it described a payload `arm.py` never produced and nothing
  validated, so it was a trap rather than documentation.

## Known problems, costs, and things I would flag

1. **`stats_table.schema.json` is documentation, not validation.** Nothing checks
   a stats table against it, and it has drifted: `subgroup_size`, `provenance`
   and the twelve ACO counters are all real columns now and none of them appear
   in the schema. Either validate in `stats.run()` or accept that this file is a
   comment — but say which.
2. **Only `session_manifest` carries a version.** `stats_table` has no
   `schema_version`, so future code cannot detect an older layout; it will read
   missing columns as null and carry on. That matters because `compare.py` joins
   by column name, so a rename becomes a silently missing metric.

# Track A Capture Instructions for remnant2__ward13_idle__20260405_120000

## Tool Resolution

- renderdoccmd: missing -> <not found>
- qrenderdoc: missing -> <not found>

## Capture Order

1. Launch the game with the configured Proton and graphics settings profile.
2. Reach the named scene and stabilize camera / motion before capture.
3. Trigger a RenderDoc frame capture manually.
4. Save at least one screenshot that clearly identifies the scene state.
5. Record manual notes about camera anchor, movement, NPC state, and any transient effects.
6. Preserve the `.foz` files generated from the same session window for Track B.

## Per-Game Scene Hints

- Known scene labels: ward13_idle, yaesha_open_area, combat_encounter_dense_effects
- Proton notes: Use the same Proton version across comparison runs when possible.
- Executable notes: Confirm the exact Steam launch path and whether any anti-cheat or launcher layer affects capture.

## Recommended Launch Options

- `Keep the graphics settings profile label stable across repeated captures.`
- `Preserve any RADV_DEBUG or pipeline cache flags in `capture_environment.json`.`

## Manual Capture Notes

- A sample `.foz` already exists in `src/shaders/remnant2/steamapp_pipeline_cache.foz` and can be used to validate Track B.
- If the scene is dynamic, document what must remain unchanged for repeatability.

## Expected Canonical Session Slots

- RenderDoc captures: `analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/track_a_frame_capture/renderdoc`
- Screenshots: `analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/track_a_frame_capture/screenshots`
- Frame markers / draw summaries: `analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/track_a_frame_capture/frame_markers`
- Capture logs: `analysis/games/remnant2/sessions/remnant2__ward13_idle__20260405_120000/track_a_frame_capture/logs`

## Expected `.foz` Collection Patterns

- `~/.steam/steam/steamapps/shadercache/1282100/fozpipelinesv6/*.foz`
- `~/.local/share/Steam/steamapps/shadercache/1282100/fozpipelinesv6/*.foz`
- `src/shaders/remnant2/steamapp_pipeline_cache.foz`

## Honest Limitations

- This workflow prepares metadata and canonical storage; it does not automate in-game navigation.
- It does not assume RenderDoc can be fully automated through Proton for every title.
- Exact Track A to Track B pipeline matching remains unresolved until explicit hashes or manual annotations are imported.
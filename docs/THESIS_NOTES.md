# Thesis Notes

Consolidated working notes for the TCC. Historical procedures are kept here for provenance;
the current automated workflow lives in [../DOMAIN.md](../DOMAIN.md) and the `tcc` CLI.
(`docs/WORKFLOWS.md` was referenced here but never existed; corrected 2026-08-20.)

## Investigation focus

- Why RDNA3 (RX 7800 XT, Navi 32, gfx1101) shows uneven gen-over-gen gains vs RDNA2.
- Hypotheses: compiler-managed ALU **issue distance** via `s_delay_alu`,
  VOPD dual-issue underutilization, VGPR pressure / occupancy limits.
  ⚠️ **Corrected 2026-08-20.** This line used to read "*via `s_delay_alu` (no
  hardware interlocks)*". That framing is refuted: both RDNA2 §4.4 and RDNA3
  §5.6 carry the identical sentence that shader hardware resolves most data
  dependencies. Interlocks were **not** removed. What GFX11 changed is that the
  SIMD frontend no longer switches waves on an ALU stall, so the cost is paid in
  occupancy rather than correctness — see [PREMISE.md](PREMISE.md) §2 and
  [STATE_OF_THE_ART.md](STATE_OF_THE_ART.md) §2.
- Method: correlate high-gain vs low-gain workloads; compare stock ACO vs custom-modified
  ACO builds; not to "prove a flaw" but to measure which characteristics correlate with gains.

## Historical: manual Remnant II capture recipe (pre-`tcc`)

This was the manual procedure drafted before the automated pipeline existed. It is superseded
by `tcc session new` → `tcc foz snapshot` → `tcc arm` → `tcc launch` → `tcc foz delta`,
but documents the underlying mechanics:

1. Record `.foz` state BEFORE launching the game:
   ```bash
   APPID=1282100
   find ~/.steam/steam/steamapps/shadercache/${APPID} \
        ~/.local/share/Steam/steamapps/shadercache/${APPID} \
        -path '*/fozpipelinesv6/*' -type f \
        -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' 2>/dev/null | sort > foz_before.txt
   ```
2. Steam launch options for RenderDoc capture: `ENABLE_VULKAN_RENDERDOC_CAPTURE=1 %command%`
   (now handled by the `capture-rdc` profile through `bin/tcc-launch.sh`).
3. Launch game via Steam with qrenderdoc open → reach scene → File → Attach to Running
   Instance → select the Proton process (`wine64-preloader`) → trigger capture → save
   `.rdc` + screenshot.
4. Record `.foz` state AFTER the run (same find command) and diff to identify the cache
   file that changed during the run window. That file is the session's `.foz` evidence.
5. Fossilize `.foz` is pipeline/object state serialization, not scene replay — linkage to
   the captured frame is by run window, not visual extraction.

Known workaround if RenderDoc capture fails under recent desktops (Gamescope WSI clash):

```
ENABLE_GAMESCOPE_WSI=0 ENABLE_VULKAN_RENDERDOC_CAPTURE=1 %command%
```

## Abandoned approach: GFXReconstruct (for the record)

API-stream capture via GFXReconstruct was abandoned after repeated failures inside
Steam's Pressure Vessel container: 32-bit Wine pre-loader vs 64-bit layer ELF mismatch,
VKD3D-Proton allocator vs page-fault memory tracking collisions, and container read/write
path blocks. RenderDoc (Valve-integrated layer) + `.foz` delta mining replaced it.
The vendored `gfxreconstruct/` tree was deleted in the 2026-07 rework.

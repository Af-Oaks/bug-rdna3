# Shaderbench — executing real game shaders as a deterministic workload

**Goal:** turn the shaders captured in a game's `.foz` into a repeatable, game-free GPU
benchmark. Not to recreate the scene — to recreate the *burden*: run the actual shader code
the game compiled, under a fixed synthetic load, and time it on the GPU.

This gives a **third measurement axis** that is independent of both existing metrics:

| | what it measures | deterministic? | needs the game? |
|---|---|---|---|
| Metric 1 — static stats | what the compiler *emitted* (VGPRs, VOPD, occupancy) | yes | no |
| **Metric 3 — shaderbench** | **what that code actually *costs* the GPU** | **yes (±1–2%)** | **no** |
| Metric 2 — game FPS | what the player experiences | no (±3–5%) | yes |

Metric 3 is the piece that makes the thesis falsifiable: it confronts the static prediction
with measured GPU time on the *same shaders*, with zero scene variance. If ACO reports fewer
VGPRs and better occupancy but the shader does not get faster, Metric 3 says so — a game
benchmark never could, because scene noise swamps a 2% shader win.

Read with [METRICS_PLAN.md](METRICS_PLAN.md) (this supersedes its §4.3 and expands PLAN.md §5
`shaderlab`, which becomes two modes: *authored* microbenchmarks for causality, and
*extracted* game shaders for realism).

---

## 1. Feasibility — verified 2026-07-28, not assumed

Object counts from `fossilize-list` on the two real caches on disk:

| tag | object | Remnant II (129 MB) | Metro EE (281 MB) |
|---|---|---|---|
| 2 | descriptor set layout | **15** | **19** |
| 3 | pipeline layout | **165** | **102** |
| 4 | shader module | 12,307 | 44,647 |
| 5 | render pass | **0** (dynamic rendering) | 6 |
| 6 | graphics pipeline | 5,035 | **102,393** |
| 7 | compute pipeline | **8,088** | 213 |
| 9 | raytracing pipeline | — | 0 |

Three things follow:

1. **The foz carries everything needed to *create* an executable pipeline** — SPIR-V modules,
   descriptor set layouts, pipeline layouts, render passes (or `VkPipelineRenderingCreateInfo`
   when the game uses dynamic rendering, as Remnant II does). What it does *not* carry is
   resource contents, descriptor bindings, vertex data, draw/dispatch counts and push-constant
   values. **Those are exactly what the harness synthesizes** — that is the whole design.
2. **The layout surface is tiny.** 15–19 descriptor set layouts and ~100–165 pipeline layouts
   cover 100,000+ pipelines. The harness only has to know how to build dummy resources for
   ~20 distinct layouts per game, not per pipeline. This is what makes the idea tractable.
3. **The two games are opposites.** Remnant II is compute-heavy (8,088 compute), Metro EE is
   graphics-heavy (102,393 graphics / 213 compute). A compute-only harness covers Remnant II
   richly and Metro barely — so the staging below is driven by the data, not by convenience.

SPIR-V extraction is also verified working:

```
fossilize-disasm <db> --target asm --module-only --filter-module <hash> --output <DIR>
```
→ writes `<DIR>/<hash>` containing SPIR-V assembly (`--output` must be a **directory**; passing
a file path fails with "Failed to write disassembly"). Round-trip to a `.spv` via `spirv-as`.
Sample module `001066027c15f420` (Remnant II): `GLCompute`, `LocalSize 64 1 1`, translated from
DXIL by vkd3d-proton — the shader whose hazards §2 describes.

*(The harness itself does not use this path — §4a shows it gets create-infos straight from the
Fossilize replayer API. Extraction stays useful for inspecting a single shader by hand.)*

## 2. The two hazards (both real, both from that same sample shader)

These are the reason this is a project and not an afternoon. Both come from vkd3d-proton
translating D3D12 — so they hit every Proton DX12 title (Remnant II, Metro EE, RE Requiem).

### 2.1 Physical storage buffer addresses (the dangerous one)

The sampled shader declares `OpCapability PhysicalStorageBufferAddresses` and contains **214**
BDA / `OpConvertUToPtr` references. vkd3d-proton lowers D3D12 descriptor heaps into **raw
64-bit GPU pointers read out of constant buffers**. There is no bounds checking on a physical
pointer — feeding garbage means a GPU page fault, a hung queue, and a possible GPU reset.

**Mitigation:** allocate one large dummy "arena" buffer (e.g. 256 MB) with
`VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT`, take its device address, aim at the **middle** so
positive and negative offsets stay in range, and **fill every constant/root buffer with that
address repeated every 8 bytes**. Any 64-bit word the shader interprets as a pointer is then
valid, whatever the offset within the CBV. Cheap, general, no per-shader knowledge needed.
Validate under `VK_EXT_device_fault` / with a queue-loss watchdog before trusting a number.

### 2.2 Bindless descriptor indexing

`RuntimeDescriptorArray` + `SPV_EXT_descriptor_indexing`: the shader indexes a descriptor array
with a value read from a buffer. Garbage index → out-of-bounds descriptor access.

**Mitigation:** `VK_EXT_robustness2` (`robustBufferAccess2`, `robustImageAccess2`,
`nullDescriptor`) plus filling the entire descriptor array with a valid dummy view, so *every*
index resolves. Robustness2 has a small, uniform cost — it applies identically to both compiler
builds, so it cancels in an A/B.

### 2.3 Honest caveat for the defense

Synthetic inputs mean synthetic memory behaviour: texture residency, cache hit rates and
divergence will differ from the real scene, so **the absolute nanoseconds are not the game's
nanoseconds**. What *is* legitimate — and is all the thesis needs — is the **relative delta
between compiler A and compiler B on the same shader with byte-identical inputs**. State it
that way, always. Metric 2 remains the ground truth for absolute frame cost.

## 3. Design

### 3.1 Selection — you do not run 100,000 pipelines

A benchmark that takes 6 hours is not a benchmark. Each game contributes ~100–300 pipelines to
the shared **corpus** (§4a), chosen by a documented, reproducible rule:

- **`run_created`** only (from `foz/delta.json`) — pipelines this scene actually compiled,
  never Steam's community pre-cache.
- ranked by the `mine.py` offender score (VGPR pressure, spills, occupancy, code size),
- plus a stratified sample across the size/stage distribution so the set is not all outliers,
- pinned into `data/corpus/corpus.json` (game, session, hash list, selection rule, tool
  versions). **The corpus is versioned data, not a query** — re-running last month's benchmark
  must select exactly the same shaders.

### 3.2 Harness (`shaderlab/harness/`, C++17, volk, no CMake)

```
data/corpus/corpus.foz  (+ corpus.json)
   │  Fossilize StateReplayer -> create-infos for modules, layouts, pipelines  (§4a)
   │  build dummy resources per LAYOUT (~20 of them), not per pipeline
   │  arena buffer + BDA pattern fill (§2.1); descriptor arrays fully populated (§2.2)
   ▼
per pipeline:  warmup  →  L1 iterations (median)  →  L2 repetitions (trimmed mean)   (§3.2a)
   compute:  vkCmdDispatch with a grid derived from LocalSize (fixed invocation budget)
   graphics: dynamic rendering to a fixed offscreen target, fullscreen triangle,
             dummy vertex buffers matching the recorded vertex input state
   ▼
run.json: per-pipeline {hash, stage, reps_ns[], discarded_ns[], mean_ns, cv_pct,
                        stable, status} + environment/clock snapshot
```

**Timing rules that make it deterministic:**
- GPU timestamps (`VK_QUERY_TYPE_TIMESTAMP`), not wall clock.
- Fixed invocation budget per shader (constant total threads), so different `LocalSize` values
  are comparable.
- Warmup before anything is recorded.
- **Repetition + trimming — see §3.2a.** Never a single sample.
- **Interleave A/B (ABABAB…) within one process run.** This is the strongest cheap control:
  it cancels thermal drift and clock ramp, which otherwise dwarf a 2% compiler effect.
- Record `power_dpm_force_performance_level`, clocks and temperature in `run.json`; if the
  level can be pinned to `high` (needs root), do it and record that it was pinned.
- Any pipeline that fails to create, faults, or times out is recorded with a `status` — never
  silently dropped. Failures are data (a compiler that rejects a pipeline is a finding).

### 3.2a Repetition policy — three levels, trimmed mean

Edge cases (a stray compositor frame, a clock transition, a scheduler hiccup) hit any single
measurement. The benchmark defends against them at three nested levels:

| level | what repeats | default | reduction |
|---|---|---|---|
| **L1 — iterations** | back-to-back dispatches of one pipeline inside one timed batch | `iterations = 200` | **median** of the per-dispatch timestamps |
| **L2 — repetitions** | the whole timed batch, re-run | `repetitions = 4` | **drop the worst (slowest), mean of the remaining 3** |
| **L3 — interleave** | the L2 repetitions of compiler A and B, alternated | `ABABABAB` | per-pipeline Δ = `mean3(B) − mean3(A)` |

L1 uses the **median**, not the mean: within a batch the noise is one-sided spikes, and the
median ignores them outright. L2 uses the **trimmed mean** requested — drop the slowest of 4,
average the other 3 — because at that level there are too few samples for a median to be stable
and the discard is doing the outlier rejection.

Config (in `config/tcc.toml`, recorded into every `run.json`):
```toml
[shaderbench]
warmup_iterations = 50
iterations        = 200   # L1
repetitions       = 4     # L2
trim_worst        = 1     # L2: how many of the slowest repetitions to discard
max_cv_pct        = 2.0   # stability gate on the kept repetitions
```

**Honesty rule, and it matters:** dropping only the *slowest* is a **one-sided trim** — it
biases the reported number optimistically, because it removes upward noise while keeping
downward noise. That is acceptable here, and standard in benchmark suites, for one specific
reason: **the identical trim is applied to both compilers, so the bias cancels in the A/B
delta.** It does *not* cancel in an absolute number, so a trimmed mean must never be reported
as "this shader costs X ns" — only as "B is X% faster than A". Anything that quotes absolute
cost uses the untrimmed distribution.

To keep the trim from hiding a real problem, every measurement records the full picture, not
just the survivor:

```json
{ "hash": "...", "stage": "compute",
  "reps_ns":      [ 41220, 41310, 41180, 47950 ],   // all 4, in run order
  "discarded_ns": [ 47950 ],                        // what the trim removed
  "mean3_ns": 41236, "cv_pct": 0.16, "stable": true,
  "iterations": 200, "median_of_iterations_ns": 41236 }
```

- If `cv_pct` over the **kept** repetitions exceeds `max_cv_pct`, the entry is marked
  `stable: false` and **excluded from the aggregate verdict** but still written out.
- If the discarded value is more than 25% above the kept mean, the run is flagged
  `outlier_suspect` — that is a machine event (thermal throttle, another process on the GPU),
  not shader noise, and it should be looked at rather than averaged away.
- `n_unstable` is reported per run. A run where many pipelines are unstable is not a valid
  measurement, however clean its mean looks.

### 3.3 Staging (driven by §1's data, not convenience)

- **Stage 1 — compute only.** No render targets, no vertex state, no attachments: just
  `vkCmdDispatch`. Remnant II gives 8,088 compute pipelines to work with, and compute is where
  the modern GPU burden lives (lighting, post, culling, upscaling). Fastest path to a real number.
- **Stage 2 — graphics.** Dynamic rendering (Remnant II records **zero** render passes, so this
  is the primary path), fixed offscreen attachments matching the pipeline's recorded formats,
  fullscreen triangle, dummy vertex buffers from the recorded vertex input state. Required for
  Metro EE to mean anything at all.
- **Stage 3 — authored microbenchmarks** (the original `shaderlab` idea: `001_vopd_saturation`
  etc.). Real shaders show *correlation*; authored shaders isolate *one variable* and give
  causality. Both modes share the harness and the ledger.

## 4. The ledger

One row per **(workload, compiler revision)**. This is the artifact the thesis is actually
built on — the progress matrix across games, synthetics and compiler changes.

`data/ledger/ledger.csv`
```
run_id, date, workload_id, workload_kind,     # game-extracted | synthetic | authored
game, scene, session_id, cohort,
compiler_rev, compiler_build_id, driver_label,   # e.g. aco@<sha>, "stock", "custom"
n_pipelines, n_failed, n_unstable,
static_score, d_vgprs_mean, d_max_waves_mean, d_spilled_sum,   # ← Metric 1 (compare.py)
bench_total_ns, bench_mean_ns, bench_max_cv_pct,               # ← Metric 3 (§3.2a trimmed)
fps_avg, fps_1pct_low, frametime_p99,                          # ← Metric 2 (when run)
notes
```

The loop:

```
  baseline    → (Metric 1 stats, Metric 3 shader time, Metric 2 FPS if available)   ledger row
  compiler change ↓
  re-run all  → (Metric 1 stats, Metric 3 shader time v2)                            ledger row
  compare rows → did the static win become a measured win?
```

Two derived questions the ledger answers directly, neither of which any single metric can:

1. **Does the static metric predict measured GPU time?** Regress `Δbench_ns` on `Δstatic_score`
   across all pipelines and revisions → R², residuals. This is a *far* stronger calibration
   than static→FPS, because both sides are deterministic and per-shader.
2. **Does the measured shader win survive into the frame?** Regress `Δfps` on `Δbench_ns`
   weighted by hotness. This is where the honest caveat of §2.3 gets quantified rather
   than hand-waved.

## 4a. Implementation — what to reuse, what to build

### Build vs reuse (all paths verified present on this machine, 2026-07-28)

| need | existing tool | verdict |
|---|---|---|
| read a `.foz`, resolve create-infos | **`libfossilize` `StateReplayer`** — `lib/Fossilize/fossilize.hpp`, already built at `build/fossilize/libfossilize.a` | **reuse** |
| shader reflection (bindings, local size) | SPIRV-Cross, already built: `build/fossilize/cli/SPIRV-Cross/libspirv-cross-{core,reflect}.a` | reuse |
| Vulkan entry points | volk, already built: `build/fossilize/cli/libvolk.a`; headers `/usr/include/vulkan` (1.3.275) | reuse |
| select which compiler runs | `VK_ICD_FILENAMES` swap — already proven by `arm.py`/`config.resolve_icd` | reuse |
| carve N pipelines out of a game foz | `fossilize-prune --filter-compute/--filter-graphics <hash>` | reuse |
| append a game's slice to the corpus | `fossilize-merge-db corpus.foz slice.foz` (hash-deduped by construction) | reuse |
| static stats for the same corpus | `fossilize-replay --enable-pipeline-stats` | reuse |
| ISA / SPIR-V text | `fossilize-disasm`; `spirv-dis`/`spirv-as`/`spirv-val` at `/usr/bin` | reuse |
| authored GLSL → SPIR-V (Stage 3) | `glslangValidator` at `/usr/bin` | reuse |
| **create dummy resources, bind, dispatch, time** | **nothing exists** | **BUILD (~850 lines C++)** |
| corpus / ledger / orchestration | — | BUILD (Python, inside `tcc`) |

**The only genuinely new code is the executor.** Everything else is orchestration.

### The key simplification: Fossilize replays the create-infos for us

`StateCreatorInterface` (fossilize.hpp:91) hands over fully-resolved structs through callbacks:
`enqueue_create_shader_module`, `enqueue_create_descriptor_set_layout`,
`enqueue_create_pipeline_layout`, `enqueue_create_render_pass{,2}`,
`enqueue_create_compute_pipeline`, `enqueue_create_graphics_pipeline`.

So the harness **does not parse the foz, does not extract SPIR-V, does not reflect layouts to
create pipelines**. It implements the interface, creates the real Vulkan objects the callbacks
ask for (exactly what `fossilize-replay` does), and then adds the part Fossilize never does:
allocate dummy resources for the layouts it just saw, bind them, dispatch, and time.

```cpp
class BenchCreator : public Fossilize::StateCreatorInterface {
  // record layouts as they arrive -> we know every VkDescriptorSetLayout the corpus needs
  bool enqueue_create_descriptor_set_layout(Hash h, const VkDescriptorSetLayoutCreateInfo *ci,
                                            VkDescriptorSetLayout *out) override {
      layouts[h] = *ci;                       // remember the binding table
      return vkCreateDescriptorSetLayout(dev, ci, nullptr, out) == VK_SUCCESS;
  }
  bool enqueue_create_compute_pipeline(Hash h, const VkComputePipelineCreateInfo *ci,
                                       VkPipeline *out) override {
      if (!want(h)) return true;              // corpus filter
      vkCreateComputePipelines(dev, cache, 1, ci, nullptr, out);
      work.push_back({h, *out, ci->layout});  // queue it for timing
      return true;
  }
  // ... modules / pipeline layouts / render passes: create and remember
};
```

### C++ layout — one responsibility per file

```
shaderlab/
├── harness/
│   ├── build.sh          # the single g++ invocation below; no CMake, no install step
│   ├── main.cpp          # CLI args, run orchestration, exit codes            (~120 lines)
│   ├── device.hpp/.cpp   # instance + device, ICD/physical-device selection,
│   │                     # required feature & extension enabling             (~120 lines)
│   ├── corpus.hpp/.cpp   # BenchCreator : Fossilize::StateCreatorInterface —
│   │                     # object creation + corpus hash filter               (~130 lines)
│   ├── resources.hpp/.cpp# arena buffer, BDA pattern fill, per-layout dummy
│   │                     # descriptor sets (§4a allocator)                    (~250 lines)
│   ├── timing.hpp/.cpp   # timestamp queries, L1/L2 repetition policy,
│   │                     # trimmed mean + CV + stability gate (§3.2a)         (~150 lines)
│   └── report.cpp        # run.json writer (hand-rolled, no JSON dependency)  (~80 lines)
└── experiments/          # Stage 3 authored GLSL only — empty until then
```

Six translation units, ~850 lines total. The types stay deliberately small:

```cpp
struct BenchConfig {              // mirrors [shaderbench] in config/tcc.toml
    uint32_t warmup_iterations, iterations, repetitions, trim_worst;
    double   max_cv_pct;
    uint64_t invocation_budget;   // fixed total threads, divided by LocalSize
};

struct PipelineEntry {            // one benchmarkable unit
    Fossilize::Hash    hash;
    VkPipeline         pipeline;
    VkPipelineLayout   layout;
    VkPipelineBindPoint bind_point;
    uint32_t           local_size[3];
    Fossilize::Hash    set_layouts[4];   // -> ResourcePool
};

struct Measurement {              // exactly what §3.2a writes out
    Fossilize::Hash       hash;
    std::vector<uint64_t> reps_ns;       // ALL repetitions, in run order
    std::vector<uint64_t> discarded_ns;  // what the trim removed
    double                mean_ns, cv_pct;
    bool                  stable;
    Status                status;        // Ok | CreateFailed | Faulted | TimedOut | Skipped
};

class ResourcePool {              // built once per descriptor set layout, ~20 of them
    VkBuffer arena; VkDeviceAddress arena_ptr;
    std::unordered_map<Fossilize::Hash, VkDescriptorSet> sets;
};
```

`Status` never collapses to a bool: a pipeline the compiler refused is a *finding*, and it
must survive into `run.json` distinctly from one that ran and was slow.

### Build, and exactly what exists afterwards

```bash
shaderlab/harness/build.sh      # wraps:
g++ -O2 -std=c++17 -I lib/Fossilize -I /usr/include \
    shaderlab/harness/*.cpp \
    build/fossilize/libfossilize.a build/fossilize/libminiz.a \
    build/fossilize/cli/libvolk.a \
    -ldl -lpthread -o shaderlab/harness/tcc-shaderbench
```

Artifacts produced by the build — **this is the complete list**:

| path | tracked? | note |
|---|---|---|
| `shaderlab/harness/tcc-shaderbench` | **gitignored** | the only build output |
| *(no object files)* | — | single `g++` invocation, no intermediate `.o` kept |
| *(no CMake cache, no install tree)* | — | nothing is installed anywhere |

Everything the harness *runs* writes under `data/` (already gitignored):
`data/corpus/`, `data/ledger/`, `data/sessions/<id>/bench/`. **No build step writes outside
`shaderlab/harness/` and `data/`.**

### The dummy-resource allocator (the actual work, ~250 lines)

Driven by the ~20 descriptor set layouts, not by the 100k pipelines:

1. One **arena** `VkBuffer`, 256 MB, `SHADER_DEVICE_ADDRESS | STORAGE | UNIFORM | TRANSFER_DST`.
   Take `vkGetBufferDeviceAddress`, aim at the **middle**: `arena_ptr = base + 128MB`.
2. Fill every uniform/constant buffer with `arena_ptr` **repeated every 8 bytes** → any 64-bit
   word the shader dereferences as a physical pointer (§2.1) lands inside the arena.
3. For each descriptor set layout, walk its bindings and allocate one dummy object per
   descriptor type — storage/uniform buffer → arena sub-range; sampled/storage image → a small
   `VK_FORMAT_R8G8B8A8_UNORM` image + view + generic sampler. For `descriptorCount > 1`
   (bindless arrays), **write the same dummy view into every slot** so any index resolves (§2.2).
4. Enable `VK_EXT_robustness2` (`robustBufferAccess2`, `robustImageAccess2`, `nullDescriptor`)
   and `bufferDeviceAddress` + `descriptorIndexing` at device creation.
5. Push constants: zero-fill, except 8-byte-aligned slots which also get `arena_ptr`.

Dispatch grid: fixed **invocation budget** (e.g. 2^22 threads) divided by the shader's
`LocalSize` (read from SPIRV-Cross reflection), so shaders with different workgroup sizes do
comparable amounts of work.

### The corpus — append-only, hash-deduped, grows per game

```
data/corpus/
  corpus.foz          # ONE merged Fossilize DB: every shader in the benchmark
  corpus.json         # sidecar metadata, one entry per pipeline hash
  slices/<game>-<session>.foz     # what each game contributed (provenance, re-mergeable)
```

`corpus.json` entry: `{pipeline_hash, tag(6|7), stage, source_game, source_session,
selection_reason, local_size, layout_hash, added_date, first_seen_rev}`.

**Adding a new game is one command** — that is the whole point:

```
tcc corpus add --session <metro-session> --top 200 --strategy offenders+stratified
```
1. reads `foz/delta.json → run_created` (only what that scene really compiled),
2. ranks with `mine.py`, takes the top N plus a stratified sample,
3. `fossilize-prune --filter-compute <h> --filter-graphics <h> …` → `slices/<game>.foz`,
4. `fossilize-merge-db data/corpus/corpus.foz slices/<game>.foz` — **Fossilize dedupes by
   content hash**, so a shader shipped in two games is stored once and benchmarked once,
5. appends the new entries to `corpus.json`.

From then on **every** `bench shaders` run automatically includes it. There is no list to
edit by hand and no per-game harness code.

### The run protocol — and one correction to the "store the baseline once" model

The plan as described was: run the original compiler once, store it, then each new compiler
runs and gets diffed against the stored numbers. **That specific part will not survive
contact with the hardware, and it is worth knowing now rather than after a month of runs.**

GPU nanoseconds are not comparable across days. Clock/power state, temperature, a kernel or
system-Mesa update, even ambient conditions move timings by more than the 2–5% compiler effect
being measured. A stored baseline from three weeks ago diffed against today's run measures the
room, not the compiler.

**So: always measure both compilers in the same run, interleaved.**

```
tcc bench shaders --corpus data/corpus --compilers stock,custom --iterations 200
```
- Both builds are exercised in one session, **ABABAB…** at slice granularity, so thermal drift
  and clock ramp affect both equally and cancel in the delta.
- The delta is only ever claimed *within* a run. That is the number that goes in the ledger.
- Preferred mechanism: `VK_ICD_FILENAMES` accepts a colon-separated list, so both RADV builds
  enumerate the same GPU as two `VkPhysicalDevice`s in one process → true per-dispatch
  interleaving. **Verify this in SB-0**; if the two ICDs conflict, fall back to
  process-level alternation (run A 5 s, B 5 s, repeat, median across slices) driven from Python.
- Re-measuring the reference build every time is cheap — it is game-free and takes minutes.

The stored history keeps all its value, just in a different role: **a drift tripwire and a
trend line**, not the basis of comparison. If today's stock numbers differ from last week's
stock numbers by more than the noise band, the *environment* changed and the run is flagged
before anyone reads the compiler delta.

### The ledger is a sparse matrix, and that is fine

Rows are keyed `(pipeline_hash, compiler_rev, run_id)`. A shader added from a new game simply
has no history before its first run. Never average across time or across the whole corpus to
get "the" number — every comparison is a per-shader, within-run pair. Report coverage
(`n_pipelines`, `n_failed`) on every row so a shrinking corpus can never masquerade as an
improvement.

```
tcc corpus add --session <id> --top 200      # new game  → new rows in the matrix
tcc bench shaders --compilers stock,custom   # new build → new column
tcc ledger show                              # games × compiler revisions
```

## 5. Task list

- **SB-0 — spike `[GPU]`.** Minimal `StateCreatorInterface` over a single-pipeline pruned foz:
  create one Remnant II compute pipeline, arena + BDA pattern fill, one dummy descriptor set,
  dispatch, timestamp. ✓ the same shader timed twice within 2%, **no GPU fault**. Also settles
  whether a colon-separated `VK_ICD_FILENAMES` exposes both RADV builds as two physical devices
  in one process. *This one experiment de-risks the entire plan — do not build anything else
  first.*
- **SB-1 — `corpus.py` + `tcc corpus add/list`.** `run_created` → `mine.py` rank + stratified
  sample → `fossilize-prune` slice → `fossilize-merge-db` into `corpus.foz` → `corpus.json`.
  ✓ adding the same session twice is idempotent (hash dedupe); adding a second game grows the
  corpus without touching the first game's entries.
- **SB-2 — harness skeleton.** `StateCreatorInterface` over `corpus.foz`, pipeline creation
  only, no timing. ✓ creates N of N corpus pipelines under both ICDs; failures reported per hash.
- **SB-3 — dummy resources + compute timing (Stage 1).** §4a allocator + fixed invocation
  budget + the §3.2a repetition policy (L1 median of 200, L2 drop-worst-of-4 mean).
  ✓ a 100-pipeline Remnant II set runs; `cv_pct` over the kept repetitions < 2% for the large
  majority; `reps_ns` + `discarded_ns` present on every entry; failures carry a `Status`,
  never dropped.
- **SB-4 — `tcc bench shaders`** wrapper: session-scoped, **interleaved ABAB across both ICDs**,
  environment/clock snapshot in `run.json`. ✓ null A/B on identical compilers shows |Δ| inside
  the noise band — the same sanity gate as Metric 1's null verdict.
- **SB-5 — ledger.** `data/ledger/ledger.csv` + `tcc ledger add/show`, sparse matrix, drift
  tripwire on the reference build. ✓ two revisions produce two comparable rows; a corpus grown
  between runs does not corrupt the comparison.
- **SB-6 — harness Stage 2 (graphics).** Dynamic rendering path + dummy attachments from the
  recorded formats + fullscreen triangle. ✓ a Metro EE graphics set runs.
- **SB-7 — correlate.** `Δstatic` vs `Δbench_ns` regression + report. ✓ R² and residuals.

**Dependencies:** SB-0 gates everything. SB-1 needs `foz/delta.json` `run_created` (built) and
`mine.py` (built). SB-4 pairs with `compare.py` (M1-C). The ledger (SB-5) needs both.

## 6. Risks

1. **GPU hang from a bad pointer** (§2.1). Mitigated by the arena pattern; SB-0 exists to find
   out early. Run the harness in a separate process with a watchdog so a queue loss does not
   take the session with it.
2. **Shaders that cannot be isolated.** Some pipelines will depend on state the foz never
   recorded and will fault or produce meaningless timings. Expected. Record `status`, report
   the coverage fraction honestly ("N of M pipelines executable"), never quietly shrink the set.
3. **Synthetic ≠ scene** (§2.3). Bounded by only ever claiming *relative* deltas from Metric 3.
4. **Selection bias.** If the workload set is only the worst offenders, the measured delta will
   not represent the frame. Hence the stratified sample in §3.1.
5. **Scope.** This is a substantial C++ Vulkan project on top of an already-large plan. Stage 1
   (compute-only, one game) is a complete, defensible thesis contribution on its own; Stages 2–3
   are extensions, not prerequisites.

# `shaderlab/` — running real game shaders on the GPU

> Human context. Read this before the code, not instead of it.
> **Update obligation:** any change under `shaderlab/` updates this file in the
> same commit. See REPOCONTEXT.md § "Folder CONTEXT.md protocol".

## Why this exists

Metric 1 measures what the compiler *emitted*. Metric 2 measures what the player
*sees*. Neither answers the question in between: **does the emitted code
actually cost the GPU less?**

A game benchmark cannot answer it either — scene noise is several percent and
swamps a 2% compiler effect. So this executes the shaders themselves, with
synthetic inputs, timed on the GPU, with no game running.

This is the only C++ in the repo. Everything else orchestrates; this is the
piece that had to be built because nothing existing does it.

## What it does

`tcc-shaderbench` replays a Fossilize database through
`Fossilize::StateCreatorInterface`, which hands back fully-resolved create-infos
— so the harness never parses the `.foz`, never extracts SPIR-V, never reflects
layouts. It creates the real Vulkan objects exactly as `fossilize-replay` does,
and then adds the part Fossilize never does: allocate the resources the shader
expects, bind them, dispatch, and time it.

The `.foz` contains no buffer contents, no descriptor bindings, no push-constant
values and no dispatch sizes. **Synthesizing all of that is the whole design**,
and it is also the whole risk.

## The two hazards, and how they actually turned out

**Raw GPU pointers.** vkd3d-proton lowers D3D12 descriptor heaps into raw 64-bit
addresses read out of constant buffers — 214 of them in one sampled Remnant II
shader. There is no bounds checking on a physical pointer. The designed
mitigation was an arena buffer whose device address is written into every 8-byte
slot, aimed at the *middle* of the allocation so positive and negative offsets
both stay in range.

**It does not work for translated D3D12 shaders, and SB-0 proved it:**

| title | API | ran | outcome |
|---|---|---:|---|
| Remnant II | vkd3d-proton | **0 of 8** | GPUVM fault at `0x800044800000`, `CLIENT_ID SQC (data)` |
| mechabellum | native Vulkan | **4 of 6** | cv 0.098%–0.263% |

The reason is structural, not a bug to fix: those shaders read pointers *and*
read their offsets from the same buffers. Filling every word with the arena
address makes the pointer valid and the offset enormous, so `base + huge` lands
outside the allocation. Nothing distinguishes a pointer word from an index word,
so no single fill pattern can satisfy both.

**Bindless indexing.** The other predicted hazard was real but tractable:
Remnant II's descriptor set layout has one binding with `descriptorCount =
1,000,000` of `VK_DESCRIPTOR_TYPE_MUTABLE_EXT` — the D3D12 heap. A shared
descriptor pool with any fixed budget returns `OUT_OF_POOL_MEMORY` on it, which
is why pools are created **per layout, sized from that layout's own bindings**.
Writes are capped at 4,096 slots; beyond that `robustness2` `nullDescriptor`
makes an unwritten slot read as zero rather than fault, and writing a million
identical descriptors would buy nothing.

## Scope, stated plainly

**Metric 3 covers native-Vulkan titles.** DX12 titles remain covered by Metric 1
(static) and Metric 2 (frame rate). That is a finding worth writing down in the
thesis — translated D3D12 shaders cannot be isolated from their descriptor heaps
— not a limitation to apologise for.

## Timing rules that make it deterministic

- GPU timestamp queries, never wall clock.
- A **fixed invocation budget** divided by the shader's own `LocalSize`, so a
  64-thread and a 256-thread shader do comparable total work.
- Dispatches inside a batch are separated by a barrier: overlapping them would
  measure the scheduler's packing, not the shader.
- Warmup before anything is recorded.
- **L1** = 200 dispatches per timed batch, reduced by *median* (in-batch noise is
  one-sided spikes, and a median ignores them outright).
- **L2** = 4 batches, *drop the slowest, mean the rest*.
- **L3** = drivers alternate at batch granularity (ABAB…), because GPU clocks
  drift over minutes by more than the compiler effect being measured.

The L2 trim is **one-sided**: it removes upward noise only, so it biases the
absolute number optimistically. That is acceptable only because the identical
trim is applied to both compilers and cancels in the delta. A trimmed mean must
never be quoted as "this shader costs X ns".

## Ground rules a future change must not break

- `Status` never collapses to a bool. A pipeline the compiler refused is a
  finding and must stay distinguishable from one that ran and was slow.
- A pipeline never vanishes from the coverage denominator. A shrinking corpus
  must never be able to masquerade as an improvement.
- The harness is always launched through `core.gpuguard` — separate process,
  hard timeout, reset detection.
- Only relative, within-run deltas are ever claimed.

## Known problems, costs, and things I would flag

1. **Stage 1 is compute-only.** Graphics needs dynamic-rendering targets, dummy
   attachments matching recorded formats, and vertex buffers from the recorded
   input state. Metro EE is 102,393 graphics against 213 compute, so it is
   almost entirely uncovered until Stage 2 exists.
2. **One bad shader used to cost its whole batch.** RADV aborts the process on a
   SPIR-V capability it does not implement (observed:
   `SpvCapabilityRawAccessChainsNV`). `_run_batch_isolating` now re-runs a dead
   batch one pipeline per process, but that is a recovery path, not prevention —
   a batch of 25 that dies costs 25 process launches to sort out.
3. **A faulted batch marks every pipeline in it `batch_faulted`,** because the
   device died somewhere inside and there is no way to tell which shader did it
   without bisecting. Those pipelines are neither passes nor confirmed failures,
   and the coverage numbers should be read with that in mind.
4. **The arena is host-visible**, chosen so the pointer pattern can be written
   from the CPU. Device-local memory would be faster to access from a shader, so
   absolute timings carry an unmeasured penalty here. It cancels in an A/B and
   is one more reason absolute numbers are not quotable.
5. **`spirv_local_size()` parses SPIR-V by hand** rather than using SPIRV-Cross,
   because three integers did not justify the dependency. It handles
   `OpExecutionMode`/`OpExecutionModeId` `LocalSize` and nothing else — a shader
   using `LocalSizeId` with specialisation constants falls back to 1×1×1 and
   gets an inflated group count.
6. **No authored microbenchmarks yet.** `experiments/` is empty. Real shaders
   show correlation; a hand-written shader isolating one variable would show
   causality, and would also serve as the fast correctness canary after a
   compiler change.

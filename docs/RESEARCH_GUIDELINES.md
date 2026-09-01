# Research guidelines — how claims are made in this project

Binding on everyone writing here, human or agent. These are not style
preferences: each one exists because breaking it produces a number that looks
publishable and is not.

Method is in [METHODOLOGY.md](METHODOLOGY.md); justification in
[PREMISE.md](PREMISE.md); vocabulary in [GLOSSARY.md](GLOSSARY.md); repository
rules in [../REPOCONTEXT.md](../REPOCONTEXT.md).

---

## 1. Every claim carries its class

Four classes. State which one you are using; the marking is the claim's warranty.

| class | means | required with it |
|---|---|---|
| **measured** | produced by a run on this hardware | session id, the command, and the sha256 of the artifact |
| **derived** | computed from measured values | the formula, and the measured inputs it consumed |
| **cited** | someone else's measurement or statement | full reference, and for performance figures: resolution, settings, driver version, date |
| **speculative** | a hypothesis, an expectation, an interpretation | the word that says so, and what would refute it |

Mixing classes inside one sentence is the most common way a defensible document
becomes indefensible. "The compiler inserts 12.85% waits, which costs
performance" silently promotes a measured count into a speculative cost. Split
it: the count is measured, the cost is unmeasured.

**A number with no class is treated as speculative** until someone attaches its
provenance.

## 2. Provenance is not optional

- Every subprocess whose output could reach the thesis runs through the recorded
  path, which snapshots **the environment the child actually received**. That
  snapshot is the only machine-checkable record of which compiler produced a
  number.
- Never trust configuration to tell you which driver loaded. Read the recorded
  environment. The two builds report different version strings; use them.
- A number quoted from memory, from a previous session's summary, or from a chat
  message is not sourced. Re-derive it or cite the artifact.

## 3. The standing prohibitions

Each of these was learned the expensive way. They are not open for
relitigation — if one seems wrong, say so explicitly and argue it, but do not
quietly write around it.

1. **A count is not a cost.** More instructions does not mean slower. A wait
   inserted where the wave was already stalled on memory costs nothing. Any claim
   that a static count implies a runtime cost requires a runtime measurement.
2. **`n = 1` is not a result.** One title is an observation. It licenses "we
   observed X in title Y", never "RDNA3 does X". Say which it is.
3. **Pipeline creation is not pipeline use.** The capture records that a shader
   was compiled, never that it was drawn. Frame capture is the only ground truth
   for what reached the screen.
4. **Never quote a trimmed mean as an absolute cost.** The trim is one-sided, so
   it biases an absolute number optimistically and cancels only in a difference.
   It is a comparison statistic, not a measurement of what a shader costs.
5. **Synthetic inputs are not scene inputs.** Isolated execution invents the data
   the shader reads, so cache behaviour and divergence are not the frame's. Only
   the relative difference between two compilers on the same shader is
   defensible.
6. **`gfx1100` is not `gfx1101`.** Navi 31 is a different chip from Navi 32. Any
   result produced against the wrong target is invalid, not approximate.
7. **Report failures with counts.** Timeouts, skipped pipelines, faulted batches,
   collapsed duplicate rows — never silently dropped. A shrinking denominator
   looks exactly like an improvement.
8. **Zero is a result.** The null test must produce zero, and a real experiment
   that produces zero is a finding. Neither is a failure to be re-run until it
   moves.
9. **Heuristic linkage is labelled as heuristic.** Exact hashes are the join key;
   anything approximate says so at the point of use, not in a footnote.

## 4. Validate the instrument before believing the instrument

No non-zero number is trusted from an instrument that has not produced its zero
first. Compare a compiler against an unmodified copy of itself; the answer must
be zero, and it must be shown that the two really are different binaries rather
than one silently loaded twice.

The same discipline applies to models: the occupancy model must reproduce the
driver's own reported occupancy for every row before any occupancy claim is made.
A model that disagrees with the hardware is wrong about the hardware.

## 5. How a finding graduates

```
observation  →  board (mapas/Board.drawio)
             →  reproduced, provenance recorded  →  ONGOING.md
             →  mechanism understood, stable     →  DOMAIN.md
             →  supports a research claim        →  METHODOLOGY.md / the document
```

Nothing skips a step. A finding that has not been reproduced does not appear in
the document, however good it looks. Findings that turn out to be wrong are
**deleted** at every level rather than annotated — this project keeps no
changelog of retracted claims, because a retracted claim that stays on the page
gets re-cited.

## 6. Writing for the document

- **Never claim a defect.** The work characterizes behaviour. "RDNA3 has a bug"
  is not a finding this method can produce; "under condition X we measure Y" is.
- **State limits in the same breath as the result**, not in a separate section
  the reader reaches after forming an impression.
- **A negative result is written with the same confidence as a positive one.** If
  forcing wave32 changes nothing measurable, that sentence is the finding and it
  gets stated plainly, not buried under a search for a framing where it looks
  better.
- **Do not import the popular account of the architecture.** Check the manual.
  The widely repeated "RDNA3 removed hazard detection" claim is not what AMD
  documents — see [PREMISE.md](PREMISE.md) §2.

## 7. For agents specifically

- Read [PREMISE.md](PREMISE.md), [METHODOLOGY.md](METHODOLOGY.md) and this file
  before writing anything that will reach the document. They are short on purpose.
- Do not invent a reference, a page number, an author or a year. An incomplete
  reference marked ⚠️ is correct behaviour; a plausible-looking fabricated one is
  the worst possible failure in academic work, because it is invisible until an
  examiner checks it.
- Do not quote a measured number you did not verify in this session. Cite the
  artifact instead, or say it is unverified.
- When asked for X and you believe X is wrong, do X and say why it is wrong.
  Complying silently is the failure mode this project's documentation exists to
  prevent.

---

## Known problems, costs, and things I would flag

1. **These rules have no enforcement mechanism.** There is no test, no linter and
   no review gate that checks a claim carries its class. They work only while
   someone applies them deliberately, which means they will be strongest at the
   start and weakest under deadline — exactly backwards from when they matter.
2. **Rule 3.2 (`n = 1`) is already being bent.** The wave32 finding is the
   project's headline result and rests on a single title. It is labelled
   everywhere, which is the correct handling, but a labelled violation repeated
   often enough starts reading as established. The corpus-wide replay is what
   retires it, and it has not been run.
3. **The graduation ladder in §5 has never been exercised end to end.** No
   finding has yet travelled from board to document, because the document does
   not exist. The process is therefore untested and may prove to have a missing
   step.
4. **"Never claim a defect" sits uncomfortably next to the project's origin.**
   The work began as an investigation into a suspected hardware problem, and the
   repository name still says so. Reframing to characterization is the right
   call, but the original motivation will keep leaking into drafts, and catching
   it is a recurring editorial cost rather than a one-time fix.

# `docs/attic/` — retired documents. **Nothing here may be cited.**

Files land here when they contain claims that were checked and found wrong, or
when everything correct in them was absorbed by a document that carries
provenance. They are kept, not deleted, because they record what was believed
and when — which is useful history and worthless evidence.

**Hard rule:** no number, table, bitfield or reference from this folder enters
the dissertation, the pre-project, or any other document without being
re-derived from a primary source first. The errors in these files are
concentrated in the *precise-looking tables* — bitfields, opcode lists,
occupancy rows — which are exactly the parts a reader trusts most and checks
least.

The live research layer is: [PREMISE](../PREMISE.md) ·
[METHODOLOGY](../METHODOLOGY.md) · [STATE_OF_THE_ART](../STATE_OF_THE_ART.md) ·
[RESEARCH_SYNTHESIS_AND_REFUTATION](../RESEARCH_SYNTHESIS_AND_REFUTATION.md) ·
[GLOSSARY](../GLOSSARY.md) · [BIBLIOGRAPHY](../BIBLIOGRAPHY.md) ·
[RESEARCH_GUIDELINES](../RESEARCH_GUIDELINES.md).

| file | why it is here | where the correct version lives |
|---|---|---|
| `outdated_research.md` | 10 of 20 audited technical claims are wrong: `S_DELAY_ALU` bitfield (all three fields wrong in position and width), dependency code 8, skip-code table truncated, SGPR count, occupancy formula and table, "scoreboarding was stripped", VOPD opcode list, VOPD source budget, `gfx1100` instead of `gfx1101`. Its prose conclusions largely survive; its numbers largely do not. | [STATE_OF_THE_ART §4](../STATE_OF_THE_ART.md) — the full claim-by-claim audit |
| `RDNA3_COMPILER_HAZARD_RESEARCH.md` | Reproduces the same wrong `S_DELAY_ALU` bitfield (`DEP0[6:0]`/`SKIP[10:7]`/`DEP1[15:11]`), the same wrong `SALU_DEP_1`=8, the same 6-opcode VOPD list and the same "3 distinct VGPR sources" budget — while presenting a "✅ Verified" matrix that lends the whole file false authority. Also carries the wrong Rau & Fisher DOI. Everything correct in it was already in PREMISE and STATE_OF_THE_ART. | [PREMISE §2](../PREMISE.md), [STATE_OF_THE_ART §1.1–1.2](../STATE_OF_THE_ART.md) |
| `things_biblio.md` | An 8-line copy-paste fragment of STATE_OF_THE_ART §3.1–3.2, cut off mid-sentence. No unique content. | [STATE_OF_THE_ART §3](../STATE_OF_THE_ART.md) |

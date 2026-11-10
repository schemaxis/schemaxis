# Pandoc transcript and caption publication review — 24 October 2026

Scope: the existing closed `schemaxis.pandoc/1` report route, strengthened for
publishing a timed transcript or caption table (literal millisecond start and end
times beside dialogue text) as HTML5 and editable DOCX. No new report field,
operation or route; the strict `--sandbox` writers are unchanged. Earlier reviews:
[route completion](2026-10-17-pandoc-completion.md) and
[hostile evidence](2026-10-24-pandoc-evidence.md).

## Contract decision

The existing table contract is sufficient and preferred: a transcript is one table
with `Start (ms)`, `End (ms)` and `Text` header cells and ordered utterance rows.
Times are text, kept exactly as written; the route does not parse, convert or
order them. The shipped example is `examples/schemaxis/pandoc-transcript.json`.
WebVTT/SRT cue syntax, speakers and word-level times are out of scope.

## Gaps found and fixed

Each was reproduced by a host test that failed on the unchanged source (36 failures
plus one error before the fix) and now passes.

| Gap | Fix |
| --- | --- |
| Planning accepted bidirectional overrides/embeddings/isolates, zero-width space, word joiner, byte order mark, invisible operators, tag characters and noncharacters in text and cells | `INVALID_REPORT_TEXT` at the cell location; ZWJ/ZWNJ and directional marks used by Persian, Hebrew, Arabic, Indic and emoji text, and non-Latin script, stay accepted |
| The table header row was not verified: HTML flattened every `tr`, DOCX never checked `tblHeader` and the readback flattened head/body/foot, so a demoted or doubled header, footer rows or wrong cell elements verified | HTML `thead`(one `th` row) then `tbody`(`td` rows), DOCX flagged first row only, exact grid width, readback one head row, one body, no footer/row-head columns |
| A DOCX cell split over several paragraphs, a nested table or hidden run content (`rPr` colour/vanish, symbols, unreviewed run children, text attributes) verified because cell text was a concatenation of every `w:t` | One `tcPr` plus one plain-text paragraph per cell; paragraph/run grammar allowlist, with only Pandoc's `rFonts w:hint="eastAsia"` run property allowed (found necessary on real Han text) |
| HTML heading/paragraph text was compared after whitespace normalisation, so doubled spaces, non-breaking spaces or newlines passed | Exact comparison; native 3.12.1 output still verifies |
| Nested elements inside HTML table cells were ignored by the text comparison | Cells must hold text only |
| `word/styles.xml` was not examined, so a replaced style could hide all compact (table) paragraphs | SHA-256 fingerprint of the reviewed 3.12.1 default held in trusted code, like the stylesheet; checked when the part is present |

Real-output regression found and fixed during the work: the first run-property
rule rejected the East Asian font hint Pandoc adds to Han text; caught by running
the example natively, then covered by a host test.

## Native observations (newly run, 24 October 2026, unregistered)

Official Pandoc 3.12.1 Linux x86-64 binary (SHA-256 matches the retained
provenance record). `tools/qualify_pandoc.py` passed: baseline, variant and the new
`interview-transcript` case, workflow reuse/invalidation, finite composition,
timeout and cancellation, 21 earlier refreshed-hash probes and 11 new transcript
probes (timestamp, unit label, header cell type, doubled space, zero-width,
nested cell element in HTML; timestamp, removed header flag, split cell, hidden
run, hidden-by-style in DOCX), all rejected as `VERIFICATION_FAILED`. The qualifier
also checks the retained HTML, DOCX and fresh readback against literal
expectations written in the qualifier, independently of the adaptor's model, plus
digit-literal, ascending, contiguous millisecond times. The qualifier's refusals
check the fault code, so each probe's intended reason is not individually asserted.
A multilingual run (Hebrew, Arabic, Devanagari, ZWJ emoji, Hangul/kana, Latin
accents, Thai, Greek, Cyrillic) also succeeded and verified; it is not part of the
qualifier. The receipt was **not** registered: the root owner refreshes the
source-bound `qualification.json`, which is now stale. The 3.7.0.2 distribution
build still cannot write DOCX under `--sandbox`; nothing was relaxed.

## Checklist

| ID | Result |
| --- | --- |
| registration | Unchanged route and decisions; scope text updated |
| schema | No declaration change; table/cell limits unchanged |
| semantics | Hostile Unicode refusal with cell locations; tests above |
| native-mapping | Same Header/Para/Table AST and writers; readback structure now checked |
| execution | Verifier tightened; native 3.12.1 acceptance and forged-evidence probes |
| discovery | Transcript/caption keywords and two reviewed search cases (see limits) |
| guidance | Pitfall, example and cell explanation updated; audit shows 26 reviewed, 0 pending |
| help | `docs/pandoc.md` transcript section, text rules, verification and recovery |
| examples | `pandoc-transcript.json`, readiness example and native case |
| tests | `tests/unit/test_pandoc_transcript.py`, existing Pandoc tests |
| qualification | Unregistered native pass; source-bound receipt stale until root refresh |
| maintenance | `absorbedVersion` 3.12.1 unchanged; acceptance note added |

## Limits

- Not a caption-format, speaker, overlap or time-order validator; no clock-time
  parsing. Times are literal text.
- A cell is one line of at most 256 characters; a report has at most 64 rows per
  table and 128 blocks, so long transcripts must be split.
- Unicode refusal is an explicit denylist, not full confusable detection; unassigned
  and private-use code points are accepted, so homoglyph spoofing is not prevented.
- DOCX style/HTML stylesheet fingerprints bind to Pandoc 3.12.1; a later release
  requires review and requalification. Settings, theme and font parts are not
  fingerprinted.
- Layout, accessibility, PDF, rendering and Word application behaviour are not
  exercised.

Master focused closeout also excludes unmapped floating-table, section/page-size,
hidden-picture and crop controls. A host regression and four real native-package
mutants with refreshed hashes assert the corresponding refusal reasons. General
visual rendering remains outside this XML/content qualification.

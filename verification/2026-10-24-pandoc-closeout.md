# Pandoc closeout repair — 24 October 2026

Scope: the existing closed `schemaxis.pandoc/1` report route. An independent review
of the transcript work found that the DOCX styles fingerprint could be bypassed
through the package's relationships, that drawings were accepted outside declared
image paragraphs, and that the hidden-character filter refused legitimate text.
No new report field, operation or route; the sandboxed writers, the qualified 3.12.1
output and the fresh native readback are unchanged. Earlier reviews:
[route completion](2026-10-17-pandoc-completion.md),
[hostile evidence](2026-10-24-pandoc-evidence.md) and
[transcript](2026-10-24-pandoc-transcript.md).

## Gaps found and fixed

| Gap | Fix |
| --- | --- |
| Relationship targets and content types were never checked, so a `styles` relationship could point at a second style part while the pinned `styles.xml` stayed byte-identical | Each relationship part must hold exactly the reviewed types, once, with Pandoc's fixed targets (plus declared PNG media in the document part); content-type defaults and overrides must be exact; the member set is exact, so orphan parts are refused |
| `word/theme/theme1.xml` and the settings, numbering, font table, web settings, footnote, comment and app/custom property parts were never read | They join `word/styles.xml` as SHA-256 fingerprints of the reviewed Pandoc 3.12.1 bytes in trusted code (`DOCX_FIXED_PARTS`); `docProps/core.xml` must hold only the report title |
| `w:drawing` was accepted in any run, including text paragraphs and table cells, and a blip in a cell passed the media check | Drawings only in a declared image paragraph (one run, one `wp:inline`, one picture, one plain blip with no children); no anchored shapes; whole-document drawing, blip and picture counts must equal the declared images; the only `r:` reference in the body is a blip `r:embed` |
| Zero-width space and every tag character were refused, so Thai, Khmer and Myanmar text and England/Scotland/Wales flags failed | ZWSP is accepted only between Thai, Lao, Myanmar or Khmer characters; well-formed emoji subdivision flag sequences are accepted; stray tags, bidirectional embeddings/overrides/isolates and the other listed controls are still refused; ZWNJ, ZWJ, LRM, RLM and the Arabic letter mark are unchanged |

Regression found by the native run and fixed: Pandoc stores byte-identical images
once, so two pictures share one media part and relationship. The first version of
the media rule required one use per relationship and refused that real output; it
now requires every media relationship to be used, while the picture count is taken
from the blips. A host test and a qualifier case (`sharedMedia`) cover it.

## Product decision for the Unicode rule

Ordinary multilingual text must not become a security policy. The route keeps an
explicit list of unsupported formatting characters and documents it. It is not a
Unicode-safety, confusable or anti-spoofing claim, and there is no blanket
format-character (`Cf`) refusal. Soft hyphen, combining grapheme joiner and Hangul
fillers are therefore accepted and not detected, as are homoglyphs; the earlier
review asked for them to be refused, and this is a deliberate departure.

## Host results

`PYTHONPATH=src python3 -m unittest tests.unit.test_pandoc_package
tests.unit.test_pandoc_evidence tests.unit.test_pandoc_transcript
tests.unit.test_pandoc_admission`: 43 tests pass. The host DOCX fixtures are now
complete synthetic packages (`tests/unit/pandoc_docx_fixture.py`) checked by the
production inspector with the fixture's placeholder parts substituted for the
reviewed digests, so relationship, content-type, membership and drawing logic runs
unchanged. `test_pandoc_package.py` asserts the specific refusal reason for each
mutant. The full host suite was not run (outside this repair's scope).

## Native observations (newly run, 24 October 2026, unregistered)

Official Pandoc 3.12.1 Linux x86-64 binary (SHA-256 prefix `10a980df73e7fea5`, the
retained provenance record). `tools/qualify_pandoc.py` exit 0, `verified: true`:
cases `calibration-report`, `changed-cells-width-heading`, `interview-transcript`
and the new `multilingual-transcript`, timeout and cancellation, workflow reuse and
invalidation, finite composition, and 50 refreshed-hash probes, all rejected as
`VERIFICATION_FAILED`. 18 are new: 14 package/drawing mutants on the calibration
report (styles relationship re-pointed with its own part and content type, orphan
theme part, theme font edit, settings edit, retyped styles content type, external
image relationship, duplicate styles relationship, anchored and inline shapes in a
table cell, the existing image reused in a cell, a drawing in a text paragraph, an
anchored image paragraph, a transparent blip, a second picture in an image
paragraph), 2 shapes in a transcript timestamp cell, and 2 joiner/mark removals.
The new probes also assert the intended reason text, not only the fault code; the
earlier 32 probes check the code only.

The multilingual case (Hebrew with U+200F, Persian ZWNJ, Hindi ZWJ, Thai ZWSP and
three tag flags) ran natively; the qualifier compares retained HTML, DOCX and the
fresh DOCX readback with literal expectations written in the qualifier and checks
that each of those characters is present in all three. Pandoc 3.12.1 writes these
in plain runs without extra run properties, so no run-property allowance was
needed. A separate native run with an image after a text paragraph showed the
`BodyText` paragraph style, which the inspector therefore accepts beside
`FirstParagraph`. The qualifier receipt was **not** registered; the root owner
refreshes the source-bound `qualification.json`, which is stale for these changes.

## Checklist

| ID | Result |
| --- | --- |
| registration | Unchanged route and decisions |
| schema | No declaration change |
| semantics | Narrowed Unicode refusal with cell locations; exact refusal-reason tests |
| native-mapping | Same Header/Para/Table/Image AST and writers; package structure now closed |
| execution | Verifier tightened; native 3.12.1 acceptance and 50 forged-evidence probes |
| discovery | No search-case change |
| guidance | Text-rule pitfall updated |
| help | `docs/pandoc.md` text rules, verification and recovery updated; generated references are the root owner's |
| examples | `pandoc-multilingual-transcript.json` and readiness case added |
| tests | `test_pandoc_package.py`, fixture, evidence/transcript updates |
| qualification | Unregistered native pass; receipt stale until root refresh |
| maintenance | `absorbedVersion` 3.12.1 unchanged; acceptance note added |

## Limits

- XML and package checks only. Word, LibreOffice, browser rendering, bidirectional
  layout, shaping and font fallback were not exercised and nothing here is a visual
  or accessibility certification.
- The fixed-part fingerprints and exact relationship tables bind to Pandoc 3.12.1; a
  later release that changes any of them fails verification until reviewed and
  requalified.
- Unicode: explicit list only (see above); no confusable detection.
- A cell is one line of at most 256 characters; at most 64 rows per table.

# Pandoc image-width boundary — 24 October 2026

Scope: the existing closed `schemaxis.pandoc/1` report route, field `widthMm` of the
`image` block. No new field, operation, route, format or native mapping; the HTML,
DOCX and fresh-readback verifiers are unchanged. Earlier reviews:
[route completion](2026-10-17-pandoc-completion.md),
[hostile evidence](2026-10-24-pandoc-evidence.md),
[transcript](2026-10-24-pandoc-transcript.md) and
[closeout](2026-10-24-pandoc-closeout.md).

## Defect reproduced before repair

`widthMm` was declared as 10–150 and any number was planned. Against the official
Pandoc 3.12.1 binary, two ranges planned cleanly, ran every native stage and then
failed with `VERIFICATION_FAILED`, leaving a failed retained attempt:

| Authored width | Native result | Cause |
| --- | --- | --- |
| 148.17, 148.2, 149, 150 mm | DOCX width differs beyond two EMU | The DOCX writer clamps pictures to its page text width, 5334000 EMU (148.17 mm) |
| 12.3456789, 33.333333333333336, 10.000001, 80.123456 mm | HTML semantics differ | The HTML writer keeps five decimals (12.34568) |

148.0, 148.1, 80.001 and 80.01 verified, so the limits are the writers', not the
verifier's. The verifier tolerances were not changed.

## Repair

- The declared maximum is 148 mm (generated schema, guide, field guidance). A larger
  value is refused at planning as `INVALID_ARGUMENT` with the usual range location.
- A `widthMm` with more than five decimal places is refused at planning as
  `INVALID_REPORT_IMAGE`, located at `…content[n].widthMm`, with recovery text.
- Genuine legacy reports: `verify` re-plans the retained `authored.json` under the
  earlier 150 mm ceiling with no precision rule, so a retained report that really
  verified still verifies. Its evidence is inspected exactly as before; widths below
  10 or above 150, booleans and non-finite numbers are still refused there.

## Tests

`tests/unit/test_pandoc_allocation.py` (5 tests) fails on the pre-change source
(9 failures, 7 errors) and passes after: boundary and
refused widths, fault location and message, generated-schema maximum, retained
re-planning (including that `verify` uses it) and retained refusals.
`PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_pandoc*.py'`:
49 tests pass. `tools/studio_guidance.py --app pandoc --check`: 26 reviewed, 0 pending.
The full host suite and generated references were not run (integration owner).

## Native observations (newly run, 24 October 2026, unregistered)

Official Pandoc 3.12.1 Linux x86-64 binary (the qualified release; the project's
latest-release API and release page both list 3.12.1 as of this run).
`tools/qualify_pandoc.py` exit 0, `verified: true`: the four existing cases,
timeout and cancellation, workflow reuse and invalidation, finite composition,
shared media and the 54 refreshed-hash probes, all rejected as
`VERIFICATION_FAILED`. New `widthBounds` step: 148 mm and 12.34567 mm verified
natively; 149 mm and 12.3456789 mm were refused at planning before any launch. The
receipt was **not** registered and `absorbedVersion` is unchanged.

## Checklist

| ID | Result |
| --- | --- |
| registration | Unchanged route and decisions; scope text notes the width rule |
| schema | `widthMm` maximum 150 → 148; generated schema follows `OPTIONS` |
| semantics | Plan-time precision rule with located fault; retained re-plan path |
| native-mapping | No change; same AST and writers, width limits observed from Pandoc 3.12.1 |
| execution | Verifier unchanged; late native failure moved to planning |
| discovery | No search-case change |
| guidance | `widthMm` explanation updated; 26 reviewed, 0 pending |
| help | `docs/pandoc.md` and readiness recovery updated; generated references are the root owner's |
| examples | Existing examples (60, 90 mm) unchanged and valid |
| tests | New allocation tests plus existing Pandoc tests |
| qualification | Unregistered native pass; registered receipt remains stale until root refresh |
| maintenance | `absorbedVersion` 3.12.1 unchanged; acceptance note added |

## Limits

- The 148 mm and five-decimal limits bind to Pandoc 3.12.1 writer behaviour; a later
  release that changes them needs review and requalification.
- No Word, LibreOffice or browser rendering was exercised; this is not a layout
  certification.

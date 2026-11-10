# Inkscape label boundary and unsupported-runtime ordering — 2026-10-24

Scope: existing `blockDiagram` and `flowDiagram` of `schemaxis.inkscape/1`. No new
operation, native option, format or application; `absorbedVersion` stays 1.4.4.

Two defects were reproduced with host tests before repair:

- Whitespace-only labels and Unicode line separators (U+0085, U+2028, U+2029)
  planned successfully despite the single-line contract, leaving blank text that
  native measurement cannot meaningfully fit. In `flowDiagram`, a label fault was
  located at the derived rank/lane index rather than the authored box when the
  authored order differed from the derived order.
- A launcher reporting an unsupported version (for example 1.2.2) was still asked
  to query and export, and its different output surfaced as
  `VERIFICATION_FAILED` ("malformed row"), hiding the real cause.

Repair: labels are validated on authored boxes before layout and rejected with
`INVALID_LAYOUT` at `$.boxes[i].label`; ordinary text with inner/edge spaces,
non-breaking spaces and non-ASCII characters remains valid. The version visit is
now checked immediately, so an unsupported runtime stops with `UNSUPPORTED_RUNTIME`
(observed version recorded, no query/export launched, editable `diagram.svg` and a
failed `result.json` retained). A supported version with malformed query output
remains `VERIFICATION_FAILED`; a missing launcher remains `INTERPRETER_NOT_FOUND`.
Verification of retained receipts is unchanged; the published example documents
and fixed native recipe are unchanged.

Checks (host only): `tests/unit/test_inkscape_allocation.py` (6 tests; 3 failed
before repair) and `tests/unit/test_inkscape.py` (17 tests) pass. A new invalid
example (`inkscape-label-blank-invalid.json`) covers the blank label.

Native status: no Inkscape runtime was available in this review, so no native
check was run and nothing here is a native qualification. The retained 1.4.4
receipts from 2026-10-10 predate this change; the host change affects only
pre-launch validation and the ordering of an existing version check, and was not
re-qualified natively. Upstream release listing observed on 2026-10-24 shows 1.4.4
as the latest stable release, equal to the absorbed version.

Draft/human-review limits unchanged: conceptual guidance remains reference-backed,
not human-reviewed; PNG probes remain bounded raster evidence.

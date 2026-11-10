# MuPDF malformed-page-geometry strictness review

Route: `schemaxis.mupdf/1`, `review`. Scope is one bounded host-side repair to the
live-run page geometry preflight. No application, native option, native mapping,
input format or field was added, the trusted native scripts are unchanged and
`absorbedVersion` (1.28.5) is unchanged. Latest stable upstream remains 1.28.5
(official release history, checked 24 October 2026).

**Native status: unqualified for this change.** No MuPDF 1.28.5 runtime was
available. The only local `mutool` was 1.27.0, which the route correctly refuses
for execution; it was used solely to read the raw output of the unchanged
preflight script. That is not native qualification, and the registered receipt
for earlier source is not claimed for this source.

## Defect and repair

Before the repair, a source PDF with malformed page boxes was misreported or
silently altered. Raw native output retained by the preflight shows MuPDF rounds an
odd `/Rotate` (45 and 90.5 raw, rendered as a quarter turn), scales by the
magnitude of a negative `/UserUnit`, reads a non-numeric `/UserUnit` as 0, and
substitutes US Letter (612×792) for a missing or zero-area `/MediaBox` and for a
`/CropBox` that does not overlap the MediaBox.

- `/Rotate` and `/UserUnit` cases ended in a location-less `VERIFICATION_FAILED`
  whose recovery tells the user to regenerate from the authored input, although the
  source PDF is the defect.
- Missing/empty MediaBox and disjoint CropBox were accepted: a blank-looking Letter
  page was rendered, verified and published as the requested page.

Now `preflight_geometry` runs on the retained preflight output before any render and
refuses these with `PDF_GEOMETRY_INVALID` at `$.pages[N]` (the selected position),
naming the PDF page and the key, with a repair/re-export recovery. Rules use raw
retained values only: `/Rotate` a multiple of 90, `/UserUnit` in (0, 75000],
MediaBox present with positive area, CropBox (if present) overlapping it with
positive area. Reversed box corners and partial CropBox overlap stay legal. Types,
membership and non-finite values remain `VERIFICATION_FAILED` structural faults.

Legacy receipts: `metadata`/`geometry`/`verify` are unchanged, so retained evidence
that earlier releases accepted (including a Letter-substituted page) still verifies
offline; a test pins this. The new refusal is a new-run source policy.

## Checklist (changed scope only)

| Item | Result |
| --- | --- |
| registration, schema, native-mapping | Unchanged; no field or native API added. |
| semantics | New exact-fault tests for each refusal, location, valid-geometry acceptance and the structural/legacy boundary. |
| execution | Preflight runs after the inspect stage, before render; failed result retains the structured fault. |
| discovery, guidance | Unchanged: no new field or operation; guidance audit 9 reviewed, 0 pending, 0 stale. |
| help | `docs/mupdf.md` geometry and recovery text and readiness recovery name the fault. Root regenerates reference/Help. |
| examples | Unchanged baseline/variant/duplicate-page examples. |
| tests | `tests/unit/test_mupdf_allocation.py` (8 tests, 5 failed before the repair) plus the existing 8 in `test_mupdf.py`. |
| qualification | Not requalified; see native status. Source digest change makes the earlier receipt stale until the normal refresh. |
| maintenance | Latest stable 1.28.5 unchanged; no version advanced. |

## Deferred

A page-box array shorter than four numbers still makes the native script throw a
generic TypeError (`NATIVE_EXECUTION_FAILED`). Classifying it needs a trusted
native script change that requires bounded native acceptance on 1.28.5. The
`PDF_PAGE_RANGE` message also cannot state the real page count without that
change. A fresh `tools/qualify_mupdf.py` run on 1.28.5 should add a hostile
geometry probe for the new fault when a runtime is available.

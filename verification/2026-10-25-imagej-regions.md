# ImageJ measureRegions completion review

Date: 2026-10-25/26 (local, America/Winnipeg). Scope: the new `measureRegions`
operation of the `schemaxis.imagej/1` route, with its frames, regions and
calibration fields, native mapping, labelled publications, Studio starters,
discovery, guidance and the Calc typed handoff. `analyzeParticles` is unchanged
and was not re-reviewed beyond its existing cases still passing. The motivating
workflow is a product hypothesis, not demonstrated customer demand.

## Runtime and sources

- ImageJ 1.54t (`ij.jar`, official stable release; a local SHA-256 was recorded,
  and no independent publisher checksum was located, so none is claimed).
- OpenJDK 25.0.4.1 on Linux x86-64, serial, headless, private `user.home`/`tmp`/`plugins`.
- Calc handoff: LibreOffice 26.8.1.1 (ODF and OOXML read independently).
- Public API: ImagePlus, ImageStack, Roi, ImageProcessor, ImageStatistics and
  Calibration, read from the public ImageJ API documentation.
- `absorbedVersion` stays 1.54t. No qualification record was registered here.

## Checklist results

| ID | Result |
| --- | --- |
| registration | Same route and manifest; operation added; analyzeParticles preserved. |
| schema | `frames`, `regions`, `calibration` typed and bounded (2-8 frames, 1-16 regions); schema is a `oneOf` of both operations. |
| semantics | Unique safe IDs, strictly increasing finite seconds, zero-based exclusive-edge rectangles fully inside every frame, equal width/height/bit depth, aggregate budgets (4194304 px, 32 MiB, 16777216 pixel visits); all refused before native assignment with structured faults. |
| native-mapping | ImageStack (slice label = frame ID), Roi (name = region ID), `ImageProcessor.setRoi` + `ImageStatistics.getStatistics`; a fresh process uses `ImagePlus.setRoi` + `getStatistics`. Frame labels, rectangle bounds/type, calibration and source digests are read back. No RoiManager, macro, plugin or reflection. |
| execution | Isolated fixed program, timeout and cancellation (kit lifecycle), retained frames/spec/readbacks/tables, publications digest-bound, independent offline verification. |
| discovery | Reviewed search cases including a root-scope natural query and a negative (`image registration`); the ambiguous `measure area` case now lists both operations for capability search and the particle operation for Studio Add/Help (exact-phrase surfaces). |
| guidance | 65 records reviewed, 0 pending (`tools/studio_guidance.py --app imagej --check`); prose awaits editorial and domain review. |
| help | Local guide section `Measure regions`; reference and packaged Help regenerated and `--check` clean. |
| examples | Baseline and 16-bit/overlap variant, a typed Calc workflow, two Studio templates, invalid readiness examples (duplicate region, time order, bad identifier, authored macro). |
| tests | `tests/unit/test_imagej_regions.py` (host, refusal-before-native, native-boundary tamper, qualifier dispatch) and operation-aware admission tests. |
| qualification | Fresh source-bound runs below; no record registered here. |
| maintenance | `upstream.json` scope and acceptance recipe extended; absorbedVersion unchanged. |

## Native results (this change)

`tools/qualify_imagej_regions.py` (dedicated) and `tools/qualify_imagej.py` (primary, now
dispatching by operation) both ended verified on the final frozen sources.

- Route kit: 8 cases (6 particle, 2 region) with the region cases checking 73 and 36
  literal analytic values (counts, areas, raw mean/min/max, times, identity) and 10
  integrity probes each; native timeout (`RUNNER_TIMED_OUT`) and pre-launch
  cancellation (`RUNNER_CANCELLED`) verified.
- Tamper with every ordinary digest refreshed, each refused as `VERIFICATION_FAILED`
  with the semantic message and location: native count, mean, minimum, maximum, area,
  bounds, reopened mean, row order, row identity, calibration readback, rectangle
  readback, frame-label readback, source-hash readback, series configuration, retained
  source frame, authored time, published CSV cell and identity, published JSON record,
  and publication membership; plus an appended byte (refused by the readback contract).
- Typed Calc handoff (`readTypedCSV`, text `frame`/`region`, numeric columns): 4 frames x
  3 regions = 12 records; every one of 104 cells in the native ODS and OOXML read
  independently and equal to an exact pixel-enumeration oracle; captured CSV bytes
  preserved; unchanged resume reuses both jobs; changing one pixel of one frame at the
  same path invalidates the series and the workbook and the new cells match the oracle;
  the numeric-only `readCSV` control refuses the table with `INVALID_TABLE`.
- Public agent loop: the region baseline planned, executed, verified and inspected, with
  literal checks, alongside the particle cases and an invalid example fault.

A first run exposed a defect in this change (a `None` location turned precise
verification faults into a generic wrapper message). It was fixed, a probe now rejects the
generic wrapper, and the runs above are the fresh runs after the fix.

## Limits and unresolved work

- Synthetic analytic ramps only; no experimental data, no claim of suitability for any
  specific study.
- No review overlay and no editable ImageJ ROI set are produced or claimed. No sum or
  centroid is published.
- Calc's typed reader has its own record, cell and summary limits (it needs two present
  values per numeric column); R and Pandoc handoffs were not run and are not claimed.
- Sources and tools are not re-qualified for other ImageJ releases; one Java version only.
- The Calc typed reader is a provisional dependency whose own review is separate.
- The adaptor-assessment generator named in the checklist is absent from this tree, so
  assessment scopes were not refreshed here.

# ImageJ TIFF description boundary review (2026-10-24)

Scope: the `image` field of `schemaxis.imagej/1` `analyzeParticles`, host-side only.
No native mapping, option, format or `absorbedVersion` change; the route's
native qualification of 2026-10-16 neither covers nor is advanced by this note.

## Problem

The independent TIFF decoder accepted the ImageDescription tag (270) without
reading it. ImageJ 1.54t interprets a description beginning `ImageJ`
(`ij/io/TiffDecoder.saveImageDescription`, `ij/io/FileOpener.decodeDescriptionString`
and `setCalibration`): `images` above 1 makes a one-directory file a stack, and
`vunit` with a calibration function `cf` and `c0`/`c1` (or optical density, `cf=21`)
installs a density calibration. Such a file planned and decoded as one plain
plane on the host, so the mismatch appeared only after a native run, and a
stack surfaced as a generic `VERIFICATION_FAILED`.

## Change

`images.read_tiff` now reads the bounded ASCII description (it must lie inside the
file and be NUL-terminated, else `INVALID_IMAGE`) and rejects those two ImageJ
forms as `UNSUPPORTED_IMAGE` at `$.image`, reporting `tag`, `key` and `value`.
Keys that only matter once `images` exceeds 1 (`channels`, `slices`, `frames`,
`hyperstack`), calibration keys the declared calibration replaces, and
descriptions that do not begin `ImageJ` remain accepted. Strip order was
checked and is not a defect (ImageJ seeks each strip offset).

## Checklist

| ID | Result |
| --- | --- |
| registration, schema | Unchanged. |
| semantics | New exact-fault cases for the stack and density forms, a repeated-key last-wins case, CRLF and `key: value` forms, and malformed pointer/terminator. |
| native-mapping | None added. Behaviour was read from the public ImageJ 1.54t sources; the shared release list's first entry was still 1.54t on 2026-10-24. |
| execution | Planning and `reference()` fault before any Java launch; the post-run readback checks remain as a second line. |
| discovery | Not applicable: no operation, term or purpose changed. |
| guidance, help | The `image` field pitfall and `docs/imagej.md` (calibration section, fault table) describe the new rejection. Generated reference and packaged Help were not regenerated here; central regeneration is pending. |
| examples | Unchanged; fixtures reproduce byte for byte. |
| tests | `tests/unit/test_imagej_allocation.py` (5 tests) failed 8 subcases/tests on the previous decoder and passes now; `tests.unit.test_imagej_admission` (16) passes. Guidance check: 17 reviewed, 0 pending, 0 stale. |
| qualification | **Native unqualified for this change.** No ImageJ runtime was available for this allocation, so no native acceptance ran; the change only narrows host acceptance. A fresh native run and receipt remain the master's. |
| maintenance | `upstream.json` untouched; `absorbedVersion` remains 1.54t. |

## Limits

The description reader follows plain Properties lines only (no backslash
continuation or escapes), and a `cf`/`vunit` description without coefficients is
accepted because ImageJ installs no function from it. Synthetic descriptions only; no
real ImageJ-written stack or calibrated file was run through native ImageJ.

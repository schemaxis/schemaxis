# ImageMagick PNG source fault taxonomy — 24 October 2026

Scope: `schemaxis.imagemagick/1` `raster` route, host-side source PNG handling
only. No native mapping, supported format, summary schema or absorbed version
changed. No ImageMagick runtime was available for this change, so **nothing here
is native qualification**; the 17 October qualification
([completion review](2026-10-17-imagemagick-completion.md)) is unchanged and
still describes the only observed runtime.

## Issue and repair

`INVALID_RASTER_PNG` was raised both for corrupt data and for well-formed PNGs
outside the supported subset (palette, greyscale, 16-bit, interlaced, ICC, tRNS,
animation, unknown chunks, non-standard or lone gAMA/cHRM, oversize). The
recovery is different (re-capture versus deliberate re-export) and the fault had
no recovery text, no reason fields and a bare `$` location.

- `INVALID_RASTER_PNG` now means malformed only; `UNSUPPORTED_RASTER_PNG` means
  an intact chunk structure outside the subset. Classification happens only after
  CRCs, chunk order/uniqueness and sizes validate, so corruption is never labelled
  unsupported.
- Both faults are located at `$.images[N].source` and carry `observed.category`,
  `observed.feature`, `observed.reason` and a `recovery` string.
- The guide no longer claims the summary carries an output sRGB tag; it records
  the source colour declaration and authored policy, and the untagged
  encoded-sRGB interpretation is stated in the guide and readiness data.
- Acceptance set is unchanged: every PNG that decoded before decodes identically,
  every PNG rejected before is still rejected, and published-output checks are
  still `VERIFICATION_FAILED`. Receipts, `raster-summary.json`, launchers and the
  `verify` accepted-PNG set is unchanged; retained capture PNG faults now become `VERIFICATION_FAILED` with the original cause.

## Checklist (changed scope only)

| Item | Result |
| --- | --- |
| registration | Unchanged route; one new stable fault code in the existing adaptor. |
| schema | Unchanged. |
| semantics | Source classification split; 15 unsupported and 16 malformed fixtures. |
| native-mapping | Unchanged; no new mapping. Native status not re-run. |
| execution | Failed runs record the structured fault, status failed, no publications. |
| discovery | Unchanged. |
| guidance | Unchanged operation/field text; `tools/studio_guidance.py` audit run. |
| help | Guide and readiness recovery text updated; generated reference/Help need regeneration by the integrator. |
| examples | Unchanged. |
| tests | `tests/unit/test_imagemagick_allocation.py` (7 tests) and re-pointed assertions in `tests/unit/test_imagemagick.py` (7 tests). The new tests failed before the repair. |
| qualification | Not re-run; no runtime available. Existing receipt is not claimed for this change. |
| maintenance | Upstream latest release observed as 7.1.2-34 (14 October 2026), equal to the absorbed version; unchanged. |

## Limits

Host tests establish the PNG classification only. Corruption inside the
compressed pixel data of a file that is also unsupported (for example a 16-bit
image with a damaged zlib stream) is reported as unsupported, because that stream
is not inflated. No change to supported formats, colour handling or metadata
retention.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_imagemagick*.py' -v
```

The later verifier fault-wrapping repair changes error classification only; the set of accepted PNGs is unchanged.

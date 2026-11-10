# xarray named-coordinate profile reduction: completion note

Date: 25 October 2026 (client local). Scope: the new `schemaxis.xarray/1` route and its single operation
`reduceProfile`; no other adaptor is re-reviewed. This note records what was built and checked and what is
open. It is not a qualification: no `qualification.json` exists, `absorbedVersion` is null pending the
parent's accepted checks, and a successful admission or host run does not make the route native-qualified.

## Checklist results

| ID | Result |
| --- | --- |
| registration | `adaptor.json` declares `schemaxis.xarray/1`, runtime family 2026.9, hooks (query, retainedInputs, reusableInputs, resources) and the `--xarray` option. Discovered by the registry without framework changes; no native import. Host never imports xarray, NumPy or SciPy. |
| schema | Typed declarations for source, variable, coordinates (name, unit, optional range), retain and missing (value, policy, minimumValid). Generated route schemas under `docs/generated/xarray*`. The key is `coordinates` because `dimensions` and `axes` are reserved by the document framework. |
| semantics | `tests/unit/test_xarray.py` covers exact-fault rejection before native launch: dimension identity and order (permuted storage), units absent/different/calendar, duplicate/reversed/non-finite coordinates, empty and out-of-bounds ranges, fill-value mismatch, all three missing policies and thresholds, all-missing, non-finite data, unsupported attributes/variables/types, ill-conditioned cancellation, and malformed CDF structure (version, record count, overlap, gap, trailing bytes, duplicates, truncation, padding, limits). |
| native-mapping | `development.api` lists Dataset.sel, DataArray.mean, the I/O guide, the NetCDF classic format specification and the PyPI release. The worker uses open_dataset(engine='scipy'), label slice selection, where/mean, to_netcdf(NETCDF3_CLASSIC) and a fresh second-process reopen. Observed runtime recorded in each run: xarray 2026.9.0, SciPy 1.18.1, NumPy 2.5.4. |
| execution | Isolated process, resource caps, owned process-group timeout/cancel through the shared runner, input/worker/config captures and hashes, consumed-input bindings, exact publication membership and offline verification by an independent standard-library CDF-1 reader plus Fraction/fsum oracle. |
| discovery | `capabilities.py` and `search-cases.json` (NetCDF, xarray, named coordinates, depth profile, missing values, fill value, and negative regridding, Zarr and calendar queries). |
| guidance | `guidance.json`: operation and all 19 fields authored with omission/default, units, index order, range and missing-policy explanations. Author-reviewed only; an independent editorial review is still required. |
| help | `docs/xarray.md`, generated references and packaged Help regenerated in this isolated source. |
| examples | Baseline and variant plus two invalid examples (`xarray-retain-invalid.json`, `xarray-threshold-invalid.json`), original fixtures `xarray-cube.nc` and `xarray-cube-missing.nc`, Studio starters for both in `studio.json`. |
| tests | `tests/unit/test_xarray.py` (host) and `tests/unit/test_xarray_native_boundary.py` (native boundary; skipped without `SCHEMAXIS_XARRAY`). |
| qualification | `tools/qualify_xarray.py` runs the shared kit, six literal native cases, eleven refusals that precede native launch, saved-evidence controls in three separate groups (nine integrity controls caught by retained input, worker, readback, publication or receipt checks, which prove integrity not meaning; eight meaning-changing semantic mutants beyond tolerance with the native-result, readback-input, receipt and metadata bindings refreshed, each refused by the independent checker before summary publication digests are checked for an asserted cause; and two one-ulp tolerance controls, one refused as a CSV inconsistency and one accepted as within the declared tolerance, which is not a mathematical error), a workflow with reuse/same-path invalidation/offline verification, direct-path Gnuplot controls and the authored xarray -> Gnuplot `$artifact` workflow (`examples/schemaxis/xarray-profile-plot-workflow.json`) with byte-identical capture, independent SVG/PNG checks, changed-selection, reuse and same-path invalidation cases. Results are in the allocation evidence, not here. No receipt is registered by this note. |
| maintenance | `upstream.json` (latest-stable, PyPI source, `absorbedVersion` null; 2026.9.0 is the acceptance-recipe target recorded in the scope text, not an absorbed release). |

## Tolerance and scope statements

Means are unweighted arithmetic means of selected cells. Native means are accepted within
`(n + 1) * 2^-53 * mean(|x|)` of the exact rational mean and a point is refused when that bound exceeds
`1e-9 * |mean|`. The bound is first-order (second-order terms are dropped, no floor is added); when it rounds to zero the published mean must equal the nearest-rounded exact mean. Some subnormal cases instead have a representable nonzero bound. No uncertainty claim is made. Gnuplot used for the handoff was 6.0 patchlevel 2, older than
Gnuplot 6.0.5, the release absorbed by its own adaptor; it is not a source-current qualification. The Gnuplot route now declares `table` in `acceptedArtifacts` (a one-line manifest change) so the workflow edge is accepted.

Limits: at most 2048 *selected* retained points are accepted (`XR_RESOURCE_LIMIT` at `$.retain` before any native launch; the source axis may be longer); published attribute text is fixed and short, so long dimension names cannot exceed the 128-character limit.

Storage order: declarations must list dimensions in the file's stored order (a deliberate layout assertion that catches an upstream storage change; not order-agnostic, and not needed for correctness because named dimensions keep their meaning under transposition). With a matching reordered declaration a permuted cube gives the same named profile; the old order against the permuted file is `XR_DIMENSION_ORDER`.

## Open work

- Independent editorial review of guidance and docs; independent Opus code review.
- Parent-owned qualification registration, absorbedVersion decision and shared generated-file regeneration.
- No calendars, CF/geospatial meaning, weighting, alignment, interpolation, NetCDF-4, compression or remote input.

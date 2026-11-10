# xarray named-coordinate profile reduction

`schemaxis.xarray/1` reduces **one captured classic NetCDF measurement cube** to a
coordinate-labelled **profile**. A researcher selects inclusive numeric coordinate ranges, names
the dimension to keep, and averages the other named dimensions with an explicit missing-value
policy. Positional slices or a flattened CSV lose axis identity; this route keeps names, units,
order and counts in every output.

The scope is deliberately narrower than general climate or CF data. It is not an
implementation of the whole workflow roadmap: there are no calendars, geospatial or
reprojection meanings, alignment, merging or interpolation, and no remote, Dask, NetCDF-4/HDF5
or Zarr input. Isolated xarray does the work; the host never imports xarray, NumPy or SciPy.

## Start with the analytic cube

`examples/schemaxis/xarray-cube.nc` is a tiny original cube written by
`tools/xarray_fixtures.py`: `temperature(time, depth, station)` in K with
`v = 280 + 5 * depthIndex + 0.5 * timeIndex + 0.25 * stationIndex` (dyadic, so every mean is
exact). `examples/schemaxis/xarray-profile.json` keeps `depth` and averages `time` and
`station`. The literal result is `280.625 + 5 * depthIndex` with six valid cells at each of the
four depths:

```csv
depth,temperature,validCount,missingCount
0.0,280.625,6,0
10.0,285.625,6,0
20.0,290.625,6,0
30.0,295.625,6,0
```

`xarray-profile-variant.json` selects time 0 to 1 h and depth 0 to 20 m of
`xarray-cube-missing.nc` and uses `skip` with `minimumValid` 2 (means 280.375, 285.3333333333333,
290.4166666666667 with valid counts 4, 3, 3).

## Declare the cube

| Field | Meaning |
| --- | --- |
| `source` | Absolute local `.nc` path, classic CDF-1, at most 4 MiB. Bytes are captured and hashed once. |
| `variable` | `name` and `unit` of the single double data variable. The unit must equal the file's `units` attribute. |
| `coordinates` | 2 to 4 entries, **one per dimension in the exact storage order of the variable**: `name`, `unit` and an optional inclusive `range` `{minimum, maximum}` in that unit. Omitted range means the whole axis. |
| `retain` | The one declared dimension kept as the profile axis (2 to 2048 selected points). |
| `missing` | `value` (finite sentinel, equal to the file `_FillValue`), `policy` (`skip`, `propagate`, `refuse`) and, for `skip` only, `minimumValid` (default 1). |

The document key is `coordinates` because `dimensions` and `axes` are reserved by the shared
document framework. Declared order is asserted against the variable's storage order. A permuted
order is refused with `XR_DIMENSION_ORDER`. This is a deliberate layout assertion that catches an upstream
change in how the file is stored; it is not needed for correctness, because named dimensions keep their
meaning when a file is transposed. Declare the dimensions as stored, and the same named results follow.

Coordinates must be strictly increasing finite doubles (at most 4096 values, magnitude at most
1e100). Duplicates or reversed axes are refused (`XR_COORDINATE_ORDER`); reverse them upstream.
A range must lie within the stored first and last coordinate (`XR_RANGE_OUT_OF_BOUNDS`) and
contain at least one stored coordinate (`XR_SELECTION_EMPTY`). Units are asserted, never inferred
or converted: absent units are `XR_UNITS_MISSING`, a different string is `XR_UNITS_MISMATCH`, and
calendar units such as `hours since ...` are `XR_UNITS_CALENDAR`. Elapsed-time axes use plain
`h` or `s` with no calendar or epoch meaning.

## Missing values

The sentinel is a finite number in the variable's unit and must equal `_FillValue`
(`XR_FILL_MISMATCH` otherwise). NaN or infinity in the data is `XR_NONFINITE_VALUE`; it is never
treated as missing.

| Policy | Behaviour |
| --- | --- |
| `skip` | Averages valid cells only. A profile point with fewer than `minimumValid` valid cells is refused (`XR_INSUFFICIENT_VALID`). |
| `propagate` | A point with any missing cell is published with an **empty** CSV mean and the sentinel in the NetCDF; counts show why. |
| `refuse` | Any selected missing cell stops the run (`XR_MISSING_VALUES`). |

All-missing output is never published as zero: it is `XR_PROFILE_ALL_MISSING`, and fewer than two
published points is `XR_PROFILE_TOO_SHORT`. A mean equal to the sentinel is refused
(`XR_SENTINEL_COLLISION`). Valid and missing counts are always published.

## Publications

Fixed order, with index addresses for workflow handoff:

1. `profile.nc` (file): classic NetCDF with the retained coordinate, the mean (same unit, `_FillValue`),
   `validCount`, `missingCount`, preserved `units`/`long_name`/`title`, and `schemaxis_source_sha256`,
   `schemaxis_selection_sha256`, `schemaxis_reduction` global attributes.
2. `profile.csv` (table): header `<retain>,<variable>,validCount,missingCount`; shortest round-trip
   decimal text. Units are declared by the consumer and are in `xarray-summary.json`.
3. `xarray-summary.json` (text): source, per-axis (storage order, length, coordinate hash, range, selected
   indices), selection hash, profile values and counts, totals, reduction/rounding/uncertainty limits and the
   observed native runtime.

## Gnuplot handoff

`profile.csv` (artifact index 1, kind `table`) is a numeric CSV with named columns for the existing
[Gnuplot](gnuplot.md) route when no mean is missing (use `refuse`, or `skip` with a complete selection).
The Gnuplot route declares `table` as an accepted workflow artifact, so a workflow can connect the two
operations with `"source": {"$artifact": "profile", "index": 1}`. Start from
[xarray-profile-plot-workflow.json](../examples/schemaxis/xarray-profile-plot-workflow.json): replace
the cube path, keep the Gnuplot `columns` equal to the CSV header in order with units `m`, `K`, `count`,
`count` (the CSV carries no units; the consumer declares them and no conversion happens), and set the
axis ranges to enclose the profile. Gnuplot captures the producer's exact bytes into its own run directory
and the shared workflow verifier rechecks both operations and the handoff record.

`tools/qualify_xarray.py` runs this authored workflow through the public workflow scheduler with both
native locations. It requires the producer `profile.csv` to equal the consumer `captured.csv` byte for byte,
literal analytic rows, independent SVG marker positions and PNG pixels, a fresh workflow with a changed
authored selection (different means, markers and bytes), unchanged reuse, same-path source-byte
invalidation of both operations and offline verification after the cube is removed. A separate negative keeps
the missing policy apart: a `propagate` profile with an empty mean cell is refused by the Gnuplot route's own
numeric-CSV validation (`INVALID_PLOT_DATA`) before any Gnuplot process starts, so that refusal is a
host-side consumer-contract check, not a native Gnuplot parse. Earlier direct-path controls that plot a
separately produced `profile.csv` by path remain in the qualifier as additional checks, not as the handoff proof.

## Storage order and declared order

The coordinate declarations are an **assertion about the file**, so they must list the dimensions in the file's
exact storage order; they are not order-agnostic. Given a declaration that matches the stored order, the
reduction works by dimension *name*: a cube stored as `(station, depth, time)` with the declaration reordered
to `station, depth, time` gives the same named profile as the `(time, depth, station)` cube
(the qualifier runs this native case). Declaring the old order against the permuted file is refused with
`XR_DIMENSION_ORDER` before any native launch. The refusal is intentional: the route does not guess which
declared name belongs to which stored axis. Transposing the stored axes does not change what a named
dimension means; the order declaration only asserts that the file layout is the one the author reviewed.

## Limits and losses

- One local CDF-1 file: fixed dimensions only; no record dimension, NetCDF-4/HDF5, CDF-2 (64-bit offset),
  CDF-5, compression, packing, strings, categories, remote or Dask input.
- At most 4 MiB, 4 dimensions, 4096 values per axis, 262144 cells, 2048 profile points, attribute text of
  128 ASCII characters. Bounds are checked before decoding or allocation. The 2048-point limit applies to the
  *selected* retained points (`XR_RESOURCE_LIMIT` at `$.retain` before any native launch); the source axis may be
  longer, up to 4096, when the selected range holds at most 2048 points.
  Published attribute text is fixed and short (`schemaxis_reduction` does not embed dimension names; the
  reduced names are in the summary `reduced` field), so long dimension names cannot exceed the 128-character limit.
- One double variable plus its coordinate variables. Allowed attributes: `units`, `_FillValue`,
  `long_name` on variables and `title` globally. Any other attribute, variable or dimension is refused
  (`XR_ATTRIBUTE_UNSUPPORTED`, `XR_EXTRA_VARIABLE`, `XR_DIMENSION_MISMATCH`), never silently dropped.
- Offsets, counts, overlap, gaps, trailing bytes, duplicate names and non-zero padding are checked by the
  host's own bounded reader (`src/schemaxis/adaptors/xarray/cdf.py`) before any native launch.
- The mean is an **unweighted arithmetic mean** of the selected cells. It is not area, volume or time weighted
  and carries no measurement or sampling uncertainty.
- Rounding: native means are accepted within `(n + 1) * 2^-53 * mean(|x|)` of the exact rational mean.
  This is the first-order bound for sequential summation (second-order terms are dropped, so it is not a
  rigorous worst case) and it follows the data scale; no floor or loose epsilon is added. When the bound rounds
  to zero, the published mean must equal the nearest-rounded exact mean. Some subnormal cases instead have
  a representable nonzero bound. For example, `[5e-324, 0, 0]` has a zero bound and publishes the nearest-rounded
  mean `0.0`, not an invented zero. A point whose bound exceeds
  `1e-9 * |mean|` is refused as ill-conditioned (`XR_ILL_CONDITIONED`), so strongly cancelling data,
  including a non-zero-scale mean of exactly zero, is refused rather than published with a hidden error.
- Values and coordinates must be finite with magnitude at most 1e100, so sums cannot overflow.

## Runtime, public API and maintenance

The qualified native runtime is an isolated Python with exactly xarray 2026.9.0, SciPy 1.18.1 and
NumPy 2.5.4. Configure it with `--xarray` or `SCHEMAXIS_XARRAY`. The worker uses
`xarray.open_dataset(engine="scipy", decode_cf=False, mask_and_scale=False)`,
`DataArray.sel(slice)` ([Dataset.sel](https://docs.xarray.dev/en/stable/generated/xarray.Dataset.sel.html)),
`DataArray.where` and `DataArray.mean(dim, skipna)`
([DataArray.mean](https://docs.xarray.dev/en/stable/generated/xarray.DataArray.mean.html)),
`Dataset.to_netcdf(engine="scipy", format="NETCDF3_CLASSIC")` and a fresh reopen in a second process
([I/O guide](https://docs.xarray.dev/en/stable/user-guide/io.html)). Format reference:
[NetCDF classic format](https://docs.unidata.ucar.edu/netcdf-c/current/file_format_specifications.html).
A missing or different runtime is an unavailable/unsupported structured fault, never an accepted skip.

`upstream.json` tracks the latest stable xarray release. `absorbedVersion` is `null` and means an absorbed
release, not an acceptance target; the observed versions above are recorded in its scope text. It stays `null`
until the parent's independent, shared, full and native acceptance; passing host checks, documentation
admission or this note alone does not qualify the route. Run `tools/qualify_xarray.py` for bounded native
acceptance. The local Gnuplot used for the handoff was 6.0 patchlevel 2, older than the Gnuplot 6.0.5 release
absorbed by its own adaptor; the handoff is not a source-current Gnuplot qualification.

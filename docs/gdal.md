# GDAL raster windows

GDAL extracts a georeferenced pixel window and optionally changes its grid shape
with nearest-neighbour sampling (`window`), or summarises named pixel-aligned
rectangular zones of a raster into a typed table (`zonalSummary`, below). Use it for
bounded elevation, temperature and categorical raster subsets. This is a raster integration; QGIS vector operations
remain a separate workflow.

## Contract and units

Use `schemaxis.gdal/1`, operation `window`. Supply an absolute local GeoTIFF
`source`, zero-based top-left column `x` and row `y`, source `width` and `height`,
and desired `outputWidth` and `outputHeight`. All dimensions count pixels; rows
increase downward. The entire window must fit the source. Equal source/output
sizes preserve pixel spacing. Different sizes preserve the selected window's
outer extent and change spacing.

`epsg` asserts existing source CRS: 4326 means x longitude/y latitude in degrees;
3857 means x easting/y northing in metres. It never reprojects. `units` asserts
existing band values in `m`, `K` or dimensionless `1`, independently of horizontal
CRS units. `nodata` must match the source's finite sentinel and fit its dtype
exactly. These fields are checked against source metadata, never silently imposed
on a conflicting raster. The selected window must also be spatially plausible for
that CRS (below). PixelIsArea is required; the tiepoint is the upper-left
pixel corner, while sampling uses centres. Negative y spacing identifies north-up.
No vertical datum, geodesic area or area conservation is inferred.

`resampling: "nearest"` selects source index
`floor((2*i+1)*sourceSize/(2*outputSize))` for each output axis, relative to the
window. Ties select the higher index. Downsampling discards unsampled values;
upsampling repeats samples. It neither averages nor interpolates. Nodata samples
remain nodata. Summary statistics exclude nodata; an all-nodata output has zero
valid count and null minimum, maximum and mean. Bilinear and arbitrary
reprojection are deliberately deferred until independently qualified.

`lossPolicy: "strict"` refuses unsupported content. Input/output are single-band,
uncompressed classic strip GeoTIFF, UInt16, Int16 or finite Float32, north-up,
EPSG:4326 or 3857, with explicit band unit and nodata tags. Bounds: 8 MiB per raster,
262144 total source and output pixels separately, 4096 per axis. Compression,
BigTIFF, tiles, extra images/overviews/bands, masks, PixelIsPoint, rotation, custom
CRSs, additional band metadata, scale/offset, NaN and infinity are refused before
native work. TIFF strip layout, byte order and descriptive CRS citations can
change; pixels, numerical affine coordinates, CRS, units and nodata cannot.

### Spatial extent bounds

A new run refuses an EPSG:4326 window whose latitude lies outside -90 to 90 degrees
(with a 1e-6 degree tolerance), before native work. This can catch metre-scale northings
mislabelled as degrees. Only the selected window is checked; padding can be cropped away.
Longitude conventions and projected coordinates are preserved: no tile-square cutoff,
wrapping or reprojection is imposed. This plausibility check does not prove georeferencing
is correct. Retained legacy sources are not re-judged by this new-run gate.

## Zonal summaries

Operation `zonalSummary` of `schemaxis.gdal/1` measures declared rectangles of the
**captured raster's own pixel grid**. It takes the same `source`, `epsg`, `units`,
`nodata` and `lossPolicy` fields as `window` (all asserted against the source, never
imposed) plus `zones` and `missing`. A window-only field in a zonal document, or the
reverse, is `UNKNOWN_ARGUMENT`.

- `zones`: 1 to 16 objects `{id, x, y, width, height}`, reported in authored order.
  `id` is 1–32 printable ASCII characters, unique, without edge spaces, and not the
  CSV null token `\N`. It is literal text: `007` keeps its zeros and `=1+2` is never a
  formula. `x`/`y` are zero-based top-left column/row, `width`/`height` are pixels,
  and the whole rectangle must lie inside the grid. There is no polygon, world
  coordinate or reprojection input. Aggregate zone pixel visits are limited to 2 097 152.
  A source may hold up to 262 144 pixels, so eight zones that each cover a full source
  grid already reach 2 097 152 and a ninth exceeds it; overlapping zones count every
  visit again.
- Overlap is allowed. Every zone is an **independent** summary: pixels inside two zones
  are visited twice, and nothing is a union or a unique-pixel count.
- `missing` is `exclude` or `refuse`. Missing pixels are exact matches of the asserted
  and observed nodata. `exclude` reports `missing` and `coverage` (valid ÷ pixels);
  `refuse` fails with `ZONE_MISSING_VALUES` and the zone location if any zone holds one.
  A zone with no valid pixel has `valid` 0, `coverage` 0 and null `minimum`, `maximum`,
  `sum` and `mean`. Native GDAL reports such a zone with `count` 0 and `sum` 0 and no
  other keys; that exact shape is accepted and normalised to null, and any other absent
  or extra key is a verification failure. Nothing is imputed.
- `sum` is the sum of the band values of valid pixels, not an area integral; `mean` is
  the unweighted pixel mean. EPSG:4326 pixels are angular, so averages are qualified
  but no ground area, area weighting, land classification, yield, demand, uncertainty or
  location accuracy is implied. Units (`m`, `K`, `1`) are asserted and not converted.

### Native algorithm and independent checks

The host builds closed GeoJSON rectangles from your pixel indices and the source affine
(exact outer corners, same CRS) and an isolated GDAL 3.13.3 process runs the released
`raster zonal-stats` algorithm through `gdal.Run` (there is no Python wrapper class in
this release) with `stat=[count,min,max,sum,mean]`, `pixels=default` and
`include_field=[zone]`. Pixel-aligned rectangles have no fractional edge coverage, so
`default` pixel selection is unambiguous. A second process freshly reopens
`summary.geojson` and `zones.geojson` with OGR.

Verification does not trust that output. A stdlib reader enumerates **every included
pixel of every zone** from the captured TIFF and recomputes valid count, minimum, maximum
and an exact sum (`math.fsum`) and mean. It also regenerates the zone geometry from the
authored indices and the affine and requires the retained `zones.geojson`, the native
input hash and the OGR ring coordinates to match it, so a self-consistent wrong zone file
with matching native output fails. Counts must be exact integers (native floats such as
`5.0` are accepted only when integral; booleans never are), minimum and maximum equal
exact Float32/integer values. `sum` and `mean` are compared with the **exact rational sum**
`S` of the stored values (not with the host's rounded sum, so host rounding is accounted
exactly) and must lie within an allowance derived from double-precision summation: for
`n` valid values with `A=Σ|x|` and `u=2⁻⁵³`, the native sum must be within
`(n-1)u/(1-(n-1)u)·A` of `S`, which holds for any summation order, and the native mean,
which also rounds its final division, within `(that·(1+u) + u·|S|)/n` of `S/n`. The allowance
scales with the absolute values, never with the coordinate origin and never a fixed
`1e-9`.

Before any native work the host also checks that these allowances **resolve** the zone:
a zone is refused with `ZONE_SUM_UNRESOLVABLE` when either allowance exceeds `2⁻²⁶`
(about 1.5×10⁻⁸) of the exact magnitude it has to resolve. That covers an exact sum of zero
from non-zero values (`+1` and `-1`) and also partial cancellation such as Float32
`1e19, -1e19, 1e4`, where the allowance is about 44 % of the sum and a native sum scaled
by 0.6 or 0.9 would otherwise pass. The ceiling is a consistency threshold between the
native output and the host oracle: it states how finely the comparison can tell a correct
native sum from a wrong one, not how accurate the quantity is as a measurement. A forged
sum or mean is refused when it leaves the derived allowance, which is far below `2⁻²⁶` for
ordinary data (for example about `5×10⁻⁹` of the sum for `16777216, -16777215, 0.5`, which is
accepted, and far smaller for same-sign values). Choose a different zone rather than
loosening the ceiling.

The published `sum` is the correctly rounded exact sum (`math.fsum`, within `u` relative
of `S`) and the published `mean` is that sum divided by the count in double precision
(within `2u+u²` relative of `S/n`). Published zero is never signed: a zone of `-0.0` and
`0.0` publishes `0` for minimum, maximum, sum and mean in both files.

### Publications and Calc

Indices: **0** `zones-summary.csv` (`table`) and **1** `zones-summary.json` (`text`).
Native `zones.geojson` and `summary.geojson` are retained evidence, not publications.
The CSV has fixed UTF-8 LF records, a quoted header and quoted text, in authored order.
The eight columns are the measurements a reader needs to judge one rectangle of the
raster; none exists for a downstream application's convenience:

| column | kind | null | what it measures, and why it is there |
| --- | --- | --- | --- |
| `zone` | text | no | Your ID: the identity that links this row to the rectangle you authored. |
| `valid` | number (integer) | no | Pixels in the rectangle that hold a real value. It is the sample size behind every statistic below and the denominator of `mean`. |
| `missing` | number (integer) | no | Pixels equal to the asserted nodata. `valid + missing` is the rectangle's pixel count, so nothing is silently dropped. |
| `coverage` | number | no | `valid` ÷ pixels, from 0 to 1: how much of the rectangle was actually measured. A `mean` over a rectangle that is 20 % covered says less than one that is 100 % covered. It is not a positional or measurement accuracy. |
| `minimum`, `maximum` | number | yes (`\N`) | The lowest and highest valid band values, exactly as stored. Together they give the spread, which a mean alone hides. |
| `sum` | number | yes (`\N`) | The total of the valid band values. It is meaningful for additive quantities (counts, an index you intend to add) and not for elevation or temperature, where it is retained only so `mean × valid` can be checked. It is never an area integral. |
| `mean` | number | yes (`\N`) | The unweighted average of the valid band values: the typical value in the rectangle. On an EPSG:4326 grid every pixel counts equally even though ground area varies with latitude. |

`minimum`, `maximum`, `sum` and `mean` carry the band units; `valid`, `missing` and
`coverage` are unitless. A rectangle with no valid pixel reports `valid` 0 and `\N`
for the four value statistics rather than a fake zero.

Numbers are shortest round-trip decimals; `\N` is the null token. The CSV carries no
units, CRS or rectangle: `zones-summary.json` records them, plus per-zone rectangle,
pixel count and outer corners, and the publication metadata carries the typed column
list, units and missing policy. Feed it to Calc with `readTypedCSV`, declaring these
columns and `nullToken` `\N`, from a workflow `{"$artifact": "<id>", "index": 0}`.
The Calc workbook is a consumer of this table, not the reason for its columns. As a
consumer property, its Summary sheet computes spread statistics (including a sample
standard deviation) for each numeric column, which needs at least three zones with two
present measurements in that column; an all-missing zone among them is accepted. With
fewer, Calc's typed-table reader refuses with `INVALID_TABLE` rather than publishing an
empty Summary. Resuming
the same workflow with unchanged inputs reuses both jobs, and changing a nodata pixel of
the same-path source reruns both and changes the literal workbook cells. A changed zone
list or crop window is a different workflow graph: resume refuses it (`RESUME_MISMATCH`),
so it is run as a fresh workflow whose every node recomputes. The qualifier checks that
refusal and the recomputed literal values and workbook cells for a changed zone and for a
changed crop window; it makes no same-directory reuse or invalidation claim for them. A
verified `window` image artifact may feed `zonalSummary`, whose zones then use the
cropped grid.

Faults: `INVALID_ZONE` (shape, duplicate or invalid ID, outside the grid; location
`$.zones[i]`), `ZONE_MISSING_VALUES`, `ZONE_SUM_UNRESOLVABLE`, plus the existing
`INVALID_RASTER_CONTENT` (asserted CRS/units/nodata differ), `RASTER_EXTENT_INVALID`
(EPSG:4326 zone latitude outside -90..90) and `RASTER_PIXEL_LIMIT`. Recovery: re-author
the zone in the current grid, choose `exclude`, or crop away cancelling values; the
native process, deadline and cancellation limits are those of `window`.

## Run and inspect

Configure an absolute isolated Python interpreter with GDAL 3.13.3 using the
`--gdal` option or local configuration. Host planning needs only Python 3.10+
stdlib. Native jobs require POSIX resource limits and do not open a display.

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/gdal-window.json
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/gdal-window.json --output-directory output/gdal --gdal /absolute/path/to/isolated/python
PYTHONPATH=src python3 -m schemaxis verify output/gdal
```

Replace the example's source placeholder with the absolute fixture or your own
supported GeoTIFF. The elevation baseline has a literal nonzero origin, 10 m x and
negative 20 m y spacing, with two nodata pixels inside a 4×3 crop. Its independently
expected mean is 32.4. The 3×2 variant contains `[21,23,24,41,43,-9999]`, mean 30.4.
The temperature starter uses big-endian Float32 Kelvin values on an EPSG:4326 grid.

The two `window` publications are `raster.tif` and `raster-summary.json`
(`zonalSummary` publishes `zones-summary.csv` and `zones-summary.json`, above). The summary retains
CRS, affine transform, outer corners, units, nodata count and valid statistics.
A stdlib TIFF/GeoKey reader independently parses source and output and checks
every pixel against the integer sampling oracle. A separate fresh GDAL process
reopens the output and checks native readback. A successful native exit alone is
insufficient. Captured source/configuration/worker, input digests, native logs and
publication membership are bound to verification. Studio exposes editable
starters, field Help and the text summary; generic image previews may not display
GeoTIFF correctly, so use a GIS viewer for geographic visual inspection.

## Workflow and reuse

The image artifact can feed another GDAL window through a workflow `$artifact`
source reference. The downstream window uses the upstream output's pixel grid,
not the original raster's coordinates. Unchanged input bytes support reuse;
changed bytes at the same path invalidate it. Workflow verification also checks
the original source path and therefore requires that source to remain available.
Standalone verification uses the retained captured source instead. Finite
composition axes can vary
output grid dimensions after document binding. Schema evidence uses the shared
framework route, with no new private schema store.

## Recovery and limits

`INVALID_RASTER_SOURCE` requires an absolute bounded regular local GeoTIFF;
symlinks and devices are refused. `INVALID_RASTER_CONTENT` means a metadata
assertion, window extent or supported-format check failed: inspect its message,
then provide an intact supported file without silently discarding information.
`RASTER_EXTENT_INVALID` (observed CRS, axis, extent and limits are in the fault)
means the window's coordinates are impossible for its CRS: fix a mislabelled CRS or
geotransform, or crop inside the valid range. `RASTER_PIXEL_LIMIT` requires smaller source/output dimensions.
`INTERPRETER_NOT_FOUND` requires the isolated GDAL 3.13.3 interpreter.
`RUNNER_TIMED_OUT` or `RUNNER_CANCELLED` leaves an incomplete/failed result rather
than a reusable success. Each job has one deadline, owned process cancellation,
2 GiB address-space,60 s CPU and16 MiB native file-size caps. Native PROJ/GDAL data
paths are selected inside the isolated process when present under its prefix;
the user's PATH and installation are unchanged.

## Public API and maintenance

The current upstream stable release was 3.13.3 on 17 October 2026, checked against
[GDAL downloads](https://gdal.org/en/stable/download.html). The implementation uses
[Translate and TranslateOptions](https://gdal.org/en/stable/api/python/utilities.html),
[`gdal raster zonal-stats`](https://gdal.org/en/stable/programs/gdal_raster_zonal_stats.html) run through the documented `gdal.Run` entry point,
[GeoTIFF](https://gdal.org/en/stable/drivers/raster/gtiff.html) and
[affine geotransform conventions](https://gdal.org/en/stable/tutorials/geotransforms_tut.html).
[Nearest-neighbour behaviour](https://gdal.org/en/stable/programs/gdal_translate.html)
is bounded here by independently checked centre selection. Source unit readback
is explicitly restored on the output with `SetUnitType`, because Translate alone
can omit it. Run `tools/qualify_gdal.py` for native acceptance; update the absorbed
version only after host, literal pixel/geospatial, hostile evidence and lifecycle
checks pass. Receipt freshness also depends on common framework/generated Help.

Affine coordinates must remain numerically resolvable: each source/output pixel
spacing is at least 1024 double-precision ULPs at its axis origin and far edge.
Geometry with a huge origin and too-small spacing is refused. Affine verification
allows at most four ULPs per coefficient, below 1/256 pixel under this condition,
and never uses a tolerance proportional to origin magnitude. Native snapshots
have a closed typed shape: booleans cannot impersonate numeric values or pixels.
TIFF tag kind/count contracts reject malformed offsets before indexing bytes.

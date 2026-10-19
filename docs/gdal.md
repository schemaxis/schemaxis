# GDAL raster windows

GDAL extracts a georeferenced pixel window and optionally changes its grid shape
with nearest-neighbour sampling. Use it for bounded elevation, temperature and
categorical raster subsets. This is a raster integration; QGIS vector operations
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
on a conflicting raster. PixelIsArea is required; the tiepoint is the upper-left
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

The two publications are `raster.tif` and `raster-summary.json`. The summary retains
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
`RASTER_PIXEL_LIMIT` requires smaller source/output dimensions.
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

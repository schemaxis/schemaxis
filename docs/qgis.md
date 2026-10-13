# Bounded QGIS vector workflows

`schemaxis.qgis/1` adds host-safe declared vector GIS planning. Native QGIS runs in
isolated Python processes; the host retains no native imports or third-party
runtime dependencies. Select a Python executable/launcher configured for QGIS 3
with `--qgis /absolute/qgis-python` or `QGIS_PYTHON`. This is not the `qgis_process`
executable. A system QGIS Python installation can use `/usr/bin/python3` when its
QGIS providers and data are configured correctly.

## Operations

| Operation | Options | Meaning |
| --- | --- | --- |
| `readVector` | Absolute `file` | One-layer `.geojson` or `.gpkg`, CRS required |
| `reproject` | `crs`, such as `EPSG:3857` | Explicit coordinate transformation |
| `buffer` | Positive `distance`, optional `segments` (4–64, default 16) | Native geometry buffer; projected CRS in metres required |
| `clip` | `bounds: [xmin,ymin,xmax,ymax]` | Geometric intersection with a rectangle in the input layer's CRS |
| `centroid` | None | Planar area-weighted centre of each projected polygon; attributes/CRS retained |

Every operation except the reader takes `inputs: {"input": "earlierNode"}`.
`output` selects the node to publish. `preview` defaults to true. Operations are
bounded to 32 nodes, 10,000 features and one million vertices per layer. Inputs
are capped at 64 MiB in total. Only valid, nonempty 2D geometry and primitive
string/numeric/Boolean/null attributes are supported. Outputs with mixed geometry
types or no surviving features fail explicitly.

Buffering geographic coordinates is rejected rather than interpreting degrees as
metres. Select an appropriate local projected CRS for real distance/area work.
The example's EPSG:3857 coordinates near the equator are an analytic test fixture,
not a recommendation to use Web Mercator for accurate engineering measurements.
Ballpark/fallback coordinate transformations are disabled. Required grid files
and EPSG definitions remain native installation dependencies.

## Outputs and verification

The ordered publications are:

1. `result.gpkg`, kind `geospatialVector`: one layer named `result`.
2. `project.qgz`, kind `project`: an editable QGIS project referencing that layer.
3. Optional `preview.png`, kind `image`: a 640×480 map.

Retain the whole output directory. Vector geometry, semantic attributes and CRS
are compared before/after GeoPackage export, then again after the saved project
is reopened in a fresh native process. Native storage feature ids (`fid`) are
regenerated and excluded from the semantic field contract. A PNG is presentation
only, not a georeferenced raster or proof of geospatial correctness.

Receipts retain native geometry/attribute snapshots, process/runtime evidence,
source bytes, submitted worker, logs and publication hashes. Offline verification
does not require QGIS or the original input files. Workflow resume additionally
checks current external input hashes. Close/checkpoint input GeoPackages before
running; SQLite WAL/journal sidecars are rejected rather than omitted from
provenance. Shapefile bundles, rasters, remote services, authored expressions,
plugins, arbitrary algorithms and 3D terrain export are outside this release.

## Example

Replace `/absolute/path/to/qgis-sites.geojson` in
`examples/schemaxis/qgis-site-analysis.json` with the absolute path to the neighbouring
fixture. The workflow reprojects two points, buffers by 100 metres and clips a
50×50 metre study rectangle. The expected result is the eastern site's square,
with area 2,500 square metres and the original `name` attribute.

```bash
PYTHONPATH=src python3 -m schemaxis run /path/to/configured-site-analysis.json \
  --qgis /absolute/qgis-python --output-directory /fresh/site-analysis
PYTHONPATH=src python3 -m schemaxis verify /fresh/site-analysis
```

Within `schemaxis.workflow/1`, another QGIS reader can consume its `geospatialVector`
artifact and FFmpeg can consume map PNGs. Spatial vector files are not silently
converted to unreferenced CAD meshes. QGIS live console geometry and native GUI
reverse synchronisation are not implemented.

Primary references: [standalone PyQGIS](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/intro.html),
[vector APIs](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/vector.html),
[projects](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/loadproject.html).

## Native qualification

The bounded vector chain was qualified locally on QGIS **3.34.4-Prizren** using
Ubuntu packages extracted into an isolated runtime; no system installation is
required by the adaptor. `tools/qualify_media_geospatial.py --qgis /launcher
--ffmpeg /ffmpeg --directory /fresh/evidence` exercises a GeoPackage handoff,
project reopening, the analytic square above, map video, unchanged-input resume
and rejection of geographic-coordinate buffering. This is not full QGIS or
cross-platform qualification.

Adaptor-level offline verification uses retained inputs. Whole-workflow verification
and resume additionally require the original external input paths and hashes to
remain available and unchanged.

## Authored inputs

`dimensions`, `settings` and `definitions` support shared `$document` references
and the host's bounded `$expr`/`$value` composition before typed validation. Use
normal `schemaxis plan` or `run` on the authored file. Resolved distances, paths and
bounds must still meet the operation contracts above; schemas do not establish
reference validity or native success. See the [CFD handoff guide](cfd-guide.md)
for the portable site example and runtime configuration.

## Development admission

This adaptor now provides the [development kit](adaptor-development.md) delivery
contract, operation selection guidance, explicit optional-feature decisions and
an editable [acceptance example](../examples/schemaxis/qgis-admission.json).
Run the common host/native conformance recipe and inspect its scoped source-bound
receipt; structural admission alone is not native qualification. The
[current audit](design/adaptor-framework/AUDIT.md) records native availability and
exact qualification limits.

## Projected polygon centroids

`centroid` uses the public `QgsGeometry.centroid()` API to replace each polygon or
multipolygon with its planar area-weighted centre of mass. Attributes and CRS
survive the GeoPackage/project round trip. Boundaries and area do not. A centroid
may lie outside a concave polygon or inside a hole; use it for centres of mass,
not guaranteed interior labels. Geographic coordinates and non-polygon layers are
rejected at execution. Reproject explicitly before calculating centroids.

The editable [parcel example](../examples/schemaxis/qgis-centroids.json) takes the
[known rectangle](../examples/schemaxis/qgis-parcel.geojson) as an absolute input
path. Its centroid is (5,10); clipping to x=0…5 first changes it to (2.5,10). These
literal coordinates and retained attributes are checked by native kit acceptance.
See the [public geometry API](https://api.qgis.org/api/classQgsGeometry.html).

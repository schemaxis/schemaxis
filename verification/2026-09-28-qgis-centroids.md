# QGIS centroid expansion acceptance

Added the declared `centroid` operation: each projected polygon/multipolygon
becomes its planar area-weighted centre of mass, preserving semantic attributes
and CRS through GeoPackage and project save/reopen. It does not promise an interior
point or a geodesic centre. Boundaries and polygon area are explicitly lost.

The four native kit cases pass on QGIS 3.34.4 Prizren: the existing reprojection and
clip cases plus a rectangle centroid at (5,10) and a clipped variant at (2.5,10).
Coordinates are checked as independent literal WKB bytes, with attributes and CRS.
Every publication and authored/plan evidence is challenged; timeout and pre-launch
cancellation pass. Geographic polygon and point-layer inputs both fail with the
expected structured native fault. The registered QGIS receipt is source-current.

The 14 media/geospatial unit tests ran successfully (one native FFmpeg test skipped).
Reproduce with `tools/qualify_qgis_centroids.py --output-directory NEW`, selecting
the private native configuration through `SCHEMAXIS_CONFIG`. Full local evidence:
`evidence/qgis-centroid-acceptance/report.json` and `native/qualification.json`.
The observed QGIS runtime is retained; the absorbed upstream release is unchanged.

See [the operation guide](../docs/qgis.md), [editable example](../examples/schemaxis/qgis-centroids.json)
and [independent rectangle fixture](../examples/schemaxis/qgis-parcel.geojson).

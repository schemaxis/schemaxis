# GDAL geographic-latitude preflight

New EPSG:4326 runs refuse a selected window outside -90..90 degrees latitude (tolerance1e-6 degree), before capture/native execution, with RASTER_EXTENT_INVALID and observed axis/extent/limits. Legacy verification is unchanged. Longitude conventions and EPSG:3857 coordinates remain unchanged; a Web Mercator tile square is not a universal projected-coordinate validity bound. See [PROJ mathematical definition](https://proj.org/en/stable/operations/projections/webmerc.html).

The worker reproduced mislabeled metre-scale northings reaching native execution; master review narrowed its original proposed spatial bounds. Positive regressions preserve a projected northing20040000m and an unwrapped -181degree longitude. Existing metadata/content faults remain distinct. Host-only; no new native mapping or latest-native qualification. GDAL3.13.3 was unavailable. Shared Help and source-bound receipt registration belong to final integration.

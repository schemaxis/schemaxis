# ImageJ synthetic calibration targets

These two images are original synthetic test targets for the
[ImageJ particle route](../../../../docs/imagej.md). They are **not** scientific
or experimental datasets. Every particle is a union of axis-aligned pixel
rectangles, so each count, area, centroid and bounding box has a closed-form
value.

| File | Format | Intensities |
| --- | --- | --- |
| `particles-8bit.pgm` | Binary P5 PGM, 64x48, maxval 255 | Background 20; particles 150–255 |
| `particles-16bit.tif` | Uncompressed big-endian baseline TIFF, two strips, 16-bit unsigned | 100x the 8-bit values |

Both images have the same geometry: a border block, a rectangle, a square at
the inclusive-threshold boundary, a single pixel, an L shape, a ring with a 6x6
hole and a 2x2 island inside it, and two corner-touching squares.
`tools/qualify_imagej_fixtures.py` lists every rectangle and writes these exact
bytes. `--check` confirms that the committed files match.

```sh
PYTHONPATH=src python3 tools/qualify_imagej_fixtures.py --check
```

Source-bound qualification digests include these bytes, so replacing them makes
a recorded receipt stale. Do not regenerate them just to silence a stale check.
Review any change to the geometry together with the literal expectations in
`src/schemaxis/adaptors/imagej/readiness.json`.

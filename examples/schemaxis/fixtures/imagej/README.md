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

## Region-series ramps

`series/` holds original analytic planes for `measureRegions`, also not
experimental data. Every plane is 12x8 with value `base + sx*x + sy*y + st*f`
for frame `f`: `ramp8-t0..3.pgm` (8-bit, 10 + 8x + 12y + 20f) and
`ramp16-t0..2.tif` (16-bit little-endian one-strip TIFF,
1000 + 900x + 1700y + 3000f). A rectangle's mean is the ramp at its centre and
its minimum and maximum are at opposite corners, so every expectation in
`readiness.json` has a closed form. `tools/qualify_imagej_series_fixtures.py
--check` confirms the committed bytes; do not regenerate them to silence a stale
receipt.

### Fractional-mean planes

`frac8-t0..2.pgm` (8-bit) and `frac16-t0..2.tif` (16-bit little-endian one-strip TIFF)
are 9x6 planes with value `(a*x + b*y + c*f + d*x*y) mod m` for frame `f`:
`(29, 53, 17, 11, 256)` for 8-bit and `(4099, 7919, 1013, 977, 65536)` for 16-bit. The
cross term and the modulus make rectangle sums non-multiples of the pixel count, so many
means are non-terminating fractions (for example the `frac8` rectangle `(1,2,3x1)` sums to
368, 419 and 470 in the three frames: means 368/3, 419/3 and 470/3). Every expectation in
`readiness.json` is an independent Fraction of this formula, never Schemaxis or ImageJ
output. They are new files; the ramp planes above are unchanged, and
`tools/qualify_imagej_series_fixtures.py --check` covers both sets.

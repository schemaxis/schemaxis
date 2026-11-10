# ImageJ particle measurement

The `schemaxis.imagej/1` route thresholds one calibrated grayscale image and
measures every particle with ImageJ's particle analyser. It publishes a numeric
table in declared physical units (`particles.csv`) plus a provenance summary
(`particle-summary.json`), ready for a [Calc](calc.md) workbook or a later
[R](r.md) analysis. Typical uses are counting and sizing blobs, grains, pores,
colonies or cells after a fixed intensity threshold.

The same route also offers `measureRegions`: apply one named rectangle list to
a short labelled series of captured grayscale frames and publish per-frame,
per-region measurements ([Measure regions](#measure-regions)).

Complete the [authoritative checklist](adaptor-completion.md) for any later
operation or field change. The completion review is
[2026-10-16](../verification/2026-10-16-imagej-completion.md); the
`measureRegions` addition is reviewed in
[2026-10-26](../verification/2026-10-26-imagej-regions.md); the earlier
[2026-10-25](../verification/2026-10-25-imagej-regions.md) note is kept as history and
predates the region timeout/cancellation lifecycle, fractional-mean fixtures,
non-unit-area handoff and the stricter duplicate-source and budget checks.

## Runtime

The runtime is **ImageJ 1.x**, the `ij.jar` core distributed by
[imagej.net](https://imagej.net/ij/download.html). Version 1.54t, the latest
release on 2026-10-16, is the qualified runtime. Other 1.54 releases are
accepted but unqualified. `analyzeParticles` was qualified on OpenJDK 21 (2026-10-16 records, kept
as history); `measureRegions` was run natively on OpenJDK 25.0.4.1 on 2026-10-26. The adaptor runs a fixed, trusted Java source
program with the JDK
[source-file launcher](https://openjdk.org/jeps/330):

```text
java -Djava.awt.headless=true ... -cp ij.jar SchemaxisImageJParticles.java analyse ...
```

The program uses only public ImageJ classes: `PGM_Reader`/`Opener`,
`Calibration`, `ImageProcessor.setThreshold`, `ParticleAnalyzer` with count
masks, `ResultsTable` and `ImageStatistics`. It does not run macros, scripts,
plugins or the Fiji launcher. Authored values reach it only as validated
arguments. Plain ImageJ 1.x `open()`/`run()` macro commands build AWT menus and
fail under `java.awt.headless=true`, so this route uses the program instead.
[Fiji](https://imagej.net/software/fiji/) bundles the same ImageJ 1.x core, but a
Fiji installation is not this qualified runtime. Pointing `imagejJar` at Fiji's
`jars/ij-1.54*.jar` is unqualified.

Each run sets a private `user.home`, temporary folder and plugins folder inside
the run directory, so user preferences and installed plugins cannot change the
results. It also uses one processor, a 512 MiB heap and the serial collector.

Configure two locations. Java must be version 11 or newer and include the
`jdk.compiler` module; a full JDK does. ImageJ is the downloaded `ij.jar`:

```sh
PYTHONPATH=src python3 -m schemaxis configure imagej /absolute/path/to/java
# Add "imagejJar": "/absolute/path/to/ij.jar" to the same private configuration,
# or pass --imagej-jar /absolute/path/to/ij.jar when running.
```

`schemaxis configure` records only executable locations. Add the `ij.jar`
location by hand to your private `.schemaxis.local.json`, or pass `--imagej-jar`
(see [installation](installation.md)).

## Document

```json
{
  "version": "schemaxis.imagej/1",
  "operation": "analyzeParticles",
  "image": "/absolute/path/particles-8bit.pgm",
  "calibration": {"pixelWidth": 0.5, "pixelHeight": 0.5, "unit": "um"},
  "threshold": {"lower": 100, "upper": 255},
  "connectivity": "eight",
  "includeHoles": false,
  "excludeEdges": false,
  "minimumArea": 0
}
```

| Field | Meaning |
| --- | --- |
| `image` | Absolute path to one `.pgm` (binary P5, maxval 255 or 65535) or uncompressed baseline `.tif`/`.tiff` with 8- or 16-bit unsigned samples, one plane, at most 2048 px per side, 1048576 px and 16 MiB. |
| `calibration` | `pixelWidth` and `pixelHeight` (1e-6 to 1e6) in `unit` (`nm`, `um`, `mm`, `cm` or `m`). |
| `threshold` | Inclusive `lower`/`upper` raw intensities (0–255 for 8-bit, 0–65535 for 16-bit). |
| `connectivity` | `eight` (default) or `four`. |
| `includeHoles` | Count enclosed background (and enclosed particles) as part of the surrounding particle. Default false. |
| `excludeEdges` | Drop particles whose bounding box touches the image border. Default false. |
| `minimumArea`, `maximumArea` | Inclusive calibrated area window in `unit^2`. The minimum defaults to 0; with no maximum there is no upper limit. |

## Threshold

A pixel is foreground when `lower <= raw intensity <= upper`. Both bounds are
inclusive, so with `lower: 180` a region of intensity exactly 180 is kept.
Thresholds apply to stored raw values. Display range, lookup tables and file
calibration are never used. A window that covers the whole range (0–255 or
0–65535) is rejected because ImageJ treats it as one image-sized particle.
Automatic threshold methods (Otsu, IsoData and similar), background
subtraction, smoothing and watershed separation are not offered. Prepare the
image elsewhere and record that step.

## Connectivity

ImageJ finds particles in raster order: from the top row down, left to right
within a row. Each particle is numbered from 1 in that order, and the same
numbering appears in the table and the count mask.

- `eight`: pixels that touch only at a corner belong to the same particle.
- `four`: only edge neighbours connect, so corner-touching blobs stay separate.
  ImageJ always fills holes when tracing 4-connected particles, so `four`
  requires `includeHoles: true`. In ImageJ 1.54t, constructing the analyser
  with only the 4-connected flag produces empty duplicate particles. The fixed
  program always sets both flags, and `four` with `includeHoles: false` fails
  with `UNSUPPORTED_OPTION` before ImageJ starts.

With `includeHoles: true`, each particle is the region inside its outer
boundary. Interior background pixels count towards its area and intensity
statistics, and any particle lying inside a hole is absorbed rather than
reported separately. With `includeHoles: false`, a particle is exactly its
connected thresholded pixels. A particle inside a hole is then reported on its
own.

`excludeEdges` uses ImageJ's rule: a particle is dropped when its bounding box
touches any image border, even if only one pixel touches. Dropped and
size-filtered particles are counted under `rejected` in the summary.

The size window is converted to whole-pixel counts before ImageJ runs:
`minimumPixels = ceil(minimumArea / pixelArea)` and
`maximumPixels = floor(maximumArea / pixelArea)`, with a 1e-9 relative allowance
for decimal input. A window that contains no whole pixel count fails with
`INVALID_SIZE_FILTER`.

## Calibration

The declared calibration replaces whatever the file stores. ImageJ's decoded
state is still read back so that unsupported content is rejected: density
calibration (for example signed 16-bit TIFFs), inverted lookup tables or more
than one plane. A TIFF whose ImageJ-authored description declares a stack
(`images` above 1) or a density calibration (`vunit` with a calibration function
`cf` and its `c0`/`c1` coefficients, or optical density) is rejected before any
native launch as `UNSUPPORTED_IMAGE` at `$.image`, with tag 270 and the offending
key in the fault; descriptions that do not begin with `ImageJ` and other ImageJ
keys such as `unit`, `spacing`, `min` or `max` are accepted and the declared
calibration still replaces them. The description reader follows ImageJ 1.54t's
plain `key=value`, `key: value` and `key value` lines only. A description pointing
outside the file or lacking its NUL terminator is `INVALID_IMAGE`.
The origin is the top-left corner of the image, with x to the
right and y downward. Pixel `(i, j)` has its centre at
`((i+0.5)*pixelWidth, (j+0.5)*pixelHeight)`. Rectangular pixels are supported.

ImageJ stores `um` as the micro sign (`µm`). The summary keeps both the authored
`unit` and ImageJ's `nativeUnit`, and the table uses ASCII unit suffixes such as
`area_um2` and `centroidX_um`.

## Outputs

`particles.csv` (table, one row per particle in raster order):

| Column | Unit | Meaning |
| --- | --- | --- |
| `particle` | label | 1-based particle number, equal to its count-mask label. |
| `pixelCount` | pixels | Pixels in the particle (including filled holes when requested). |
| `area_<u>2` | unit² | `pixelCount * pixelWidth * pixelHeight`. |
| `centroidX_<u>`, `centroidY_<u>` | unit | Mean pixel-centre position. |
| `boundsX_<u>`, `boundsY_<u>`, `boundsWidth_<u>`, `boundsHeight_<u>` | unit | Outer edges of the axis-aligned bounding box. |
| `meanIntensity`, `minimumIntensity`, `maximumIntensity` | raw | Raw stored intensity statistics over the particle's pixels. |

`particle-summary.json` records the ImageJ and Java versions; the image format,
size, bit depth, byte order, SHA-256 and file name; the calibration and
coordinate convention; the threshold and its foreground pixel count; and the
connectivity, hole and edge settings. It also records the size window in area
and pixels, the particle count, rejected counts, total pixels and area, area
fraction and mean area. Finally it lists the column units, the count-mask digest
and the documented losses. Keep it with the table: the CSV alone does not say
how the particles were defined.

Retained evidence includes `input.pgm`/`input.tif` (a copy of the consumed
bytes), the fixed program, `native-particles.csv`, `count-mask.pgm` (16-bit
labels), `reopen-particles.csv`, both readbacks and all native logs.

## Verification

Successful exit and file existence are not accepted as proof. The verifier:

1. Decodes the input copy with an independent, dependency-free PGM/TIFF reader.
   It then predicts every particle with its own connected-component model:
   raster order, inclusive threshold, 8/4 connectivity, enclosed-hole filling
   with the complementary background connectivity, bounding-box edge exclusion
   and the whole-pixel size window.
2. Requires every native `ParticleAnalyzer` value (area, mean, min, max,
   centroid, bounds) to match that model within 1e-12 relative. Every
   count-mask label must match exactly.
3. Starts a fresh ImageJ process that decodes the retained count mask and
   re-measures each label with `ImageStatistics`. These values must equal the
   analyser's.
4. Checks the native readback: ImageJ version, decoded dimensions, bit depth,
   plane count, SHA-256 of the consumed bytes, declared calibration and unit,
   threshold, analyser option flags and pixel bounds.
5. Recomputes the publication and summary and checks every artifact and
   evidence digest.

Altering a publication, a native table, the count mask or the summary fails
verification, even when the digest records are refreshed.

## Fixtures

The acceptance images in `examples/schemaxis/fixtures/imagej/` are original
synthetic calibration targets made of axis-aligned rectangles, not
experimental data. `tools/qualify_imagej_fixtures.py` regenerates them
deterministically; run it with `--check` to confirm the committed bytes. On a
64x48 background of intensity 20, the target contains:

| Particle | Pixels | 8-bit intensity | Purpose |
| --- | --- | --- | --- |
| Border block | 20 | 255 | `excludeEdges` |
| Rectangle | 60 | 200 | Plain particle |
| Square | 64 | 180 | Inclusive threshold boundary |
| Single pixel | 1 | 150 | Size filter |
| L shape | 72 | 220 | Non-convex centroid |
| Ring with 6x6 hole | 108 (144 filled) | 160 | `includeHoles` |
| Island in the hole | 4 | 230 | Absorption when holes are filled |
| Corner-touching squares | 18 (9 + 9) | 240 | 8- versus 4-connectivity |

The 16-bit TIFF repeats this geometry with intensities multiplied by 100. It is
stored big-endian in two strips. The acceptance cases in `readiness.json` list
literal expected values derived from this geometry:

- 8 particles and 86.75 µm² at 0.5 µm per pixel.
- 5 particles and 89.5 µm² with holes filled, edge particles excluded and a
  0.5 µm² minimum area.
- 8 particles and 94.75 µm² with 4-connectivity.
- 6 particles and 59.5 µm² with the inclusive lower bound 180, or 18000 for the
  16-bit image.
- 43.375 mm² with 0.25 x 0.5 mm pixels.

```sh
PYTHONPATH=src python3 tools/qualify_imagej_fixtures.py --check
PYTHONPATH=src python3 tools/qualify_imagej.py --output-directory evidence/imagej-native \
  --java /absolute/path/to/java --jar /absolute/path/to/ij.jar
```

## Handoff

`examples/schemaxis/imagej-to-calc.json` passes the verified `particles.csv`
(artifact index 0) to Calc `readCSV`. Column names, and so units, are
preserved. An R analysis can consume the same numeric CSV later. That route is
not a qualified handoff here.

## Measure regions

A lab researcher who measures the same areas in successive microscope or
materials images should not redraw them by hand, and a bare table of numbers
loses which frame and calibration each came from. `measureRegions` takes 2-8
captured planes (`frames`, each with a unique `id`, an `image` and a
`timeSeconds`), 1-16 named rectangles (`regions`) and a declared `calibration`.

```json
{"version": "schemaxis.imagej/1", "operation": "measureRegions",
 "frames": [{"id": "T0", "image": "/data/t0.pgm", "timeSeconds": 0},
            {"id": "T1", "image": "/data/t1.pgm", "timeSeconds": 30}],
 "regions": [{"id": "core", "x": 2, "y": 1, "width": 4, "height": 3}],
 "calibration": {"pixelWidth": 0.5, "pixelHeight": 2, "unit": "um"}}
```

- **Frames.** Binary PGM or uncompressed baseline TIFF, 8 or 16-bit unsigned, all
  with the same width, height and bit depth; each file used once. Duplicates are found by
  file identity (device and inode) before anything is read, so a repeated path, a `./`
  alias or a hard link is refused as `DUPLICATE_FRAME_SOURCE`, while two distinct files with
  identical pixels (an unchanged scene) are accepted. Each plane stays within the
  single-image limits and the series within 4194304 pixels and 32 MiB; the byte total is
  decided from `fstat` sizes before any frame is read, and the pixel and visit totals from
  bounded headers before any frame is decoded.
  IDs are one letter then up to 31 letters, digits, underscores or hyphens, and
  unique. Times are finite declared seconds from 0 to 1e9 since an origin you choose
  and **strictly increase** in frame order; they are never read from the files.
- **Regions.** Zero-based top-left integer `x`, `y`, `width`, `height`; right and
  bottom are exclusive and every pixel inside counts once. A rectangle must lie
  fully inside every frame (refused, never clipped). Rectangles may overlap or nest:
  each is an independent measurement, not a partition. Nothing moves, interpolates,
  registers or tracks between frames, and there is no threshold. The work is bounded
  to 16777216 frame-pixel visits.
- **Calibration.** Declared pixel size and nm/um/mm/cm/m replace any calibration in
  the files and are read back from ImageJ. Intensities remain raw stored values;
  calibration scales only area (pixel count x `pixelWidth` x `pixelHeight`).

Outputs: `region-measurements.csv` (generic file artifact: `frame`, `region`,
`timeSeconds`, `pixelCount`, `area_<unit>2`, `meanIntensity`, `minimumIntensity`,
`maximumIntensity`; frame-major, in declared order) and
`region-measurements.json` (frame hashes and times, regions, calibration,
conventions, every record). The captured frames, series specification and native
tables are retained. No sum or centroid and **no review overlay image** is
produced: a rendered overlay would not be independently verifiable here, so none
is claimed, and the ROIs are not exported as an editable ImageJ ROI set.

The fixed Java program uses `ImagePlus`/`ImageStack` (slice label = frame ID),
`Roi` (name = region ID), `ImageProcessor.setRoi` with
`ImageStatistics.getStatistics`, and in a fresh process `ImagePlus.setRoi` with
`ImagePlus.getStatistics`. No RoiManager, macro or plugin is used.

Verification enumerates every pixel of every rectangle in every captured frame
without ImageJ and requires native count, minimum and maximum to match exactly,
mean to match the exact fraction (and area and calibrated geometry) within 1e-12
relative, row identity and order, labels, rectangle names, calibration, source
hashes and publications. Refreshing hashes cannot hide a changed measurement.
Faults retain a code and location. Most evidence checks name the retained file or field
(for example `reopen-readback.txt/region.1`, `series.spec` or `region-measurements.csv`);
some runtime-identity faults use the root, and frame-decode faults may use the authored frame location.

Two recorded fields are handled explicitly. The `jarSha256` in `runtime.json` is
cross-checked against the digest of the jar the native process itself loaded and
reported. This checks consistency between retained observations; it is not a publisher checksum
or protection against a coordinated rewrite of all those records. The stored-file calibration ImageJ read before the declared calibration
replaced it is checked against ImageJ's uncalibrated default only for files that carry no
resolution or description tags, and otherwise only for agreement between the two native
stages; it is an ImageJ observation, not an independent decode. Native stdout/stderr logs are
bound by their receipt digest only: no result is read from them, and a refreshed receipt
would hide an edit to them.

Fractional means: `examples/schemaxis/fixtures/imagej/series/frac8-t*.pgm` and
`frac16-t*.tif` (9x6, original formulas in the fixtures README) make most rectangle
sums non-multiples of the pixel count, for example a 3-pixel rectangle summing to
368 (mean 368/3 = 122.666...); the exact Fraction is compared with ImageJ's double
mean within 1e-12 relative. `examples/schemaxis/imagej-regions-fractional-to-calc.json`
uses 0.5 x 1.5 um pixels (0.75 um^2), so every workbook `area_um2` differs from
`pixelCount` and is checked as count x 0.75. The integer-mean example below is kept
as the original control, where a 0.5 x 2 um pixel makes area equal count by construction.

Calc handoff: `examples/schemaxis/imagej-regions-to-calc.json` passes the CSV
(artifact index 0) to Calc `readTypedCSV` with `frame` and `region` as text
columns and the rest as numbers. Calc's typed reader needs two present values per
numeric column and has its own table and summary limits; these are Calc's
contract, not ImageJ's. No R or Pandoc handoff is claimed.

Regions fault codes: `DUPLICATE_FRAME_ID`, `DUPLICATE_REGION_ID`,
`INVALID_IDENTIFIER`, `NON_INCREASING_TIME`, `DUPLICATE_FRAME_SOURCE`,
`REGION_OUT_OF_BOUNDS`, `SERIES_MISMATCH` and `RESOURCE_LIMIT` (aggregate
budgets), all raised before ImageJ is launched.

## Faults

| Code | Cause and recovery |
| --- | --- |
| `INVALID_RESOURCE` | `image` is relative, contains control characters, is a link or is not a regular file. Use an absolute path to a regular file. |
| `RESOURCE_NOT_FOUND` | The image cannot be opened. Check the path and permissions. |
| `INVALID_IMAGE` / `UNSUPPORTED_IMAGE` | Malformed, compressed, colour, multi-plane, signed or tagged-beyond-baseline files, including ImageJ stack or density-calibration descriptions. Convert to a plain grayscale PGM or re-save one uncompressed plane without the calibration function. |
| `RESOURCE_LIMIT` | The image or particle count exceeds the bounds. Crop or tighten the threshold or size window. |
| `INVALID_THRESHOLD` | `lower > upper`, `upper` above the bit depth, or a window that covers the whole range. |
| `UNSUPPORTED_OPTION` | `four` connectivity without `includeHoles`. |
| `INVALID_SIZE_FILTER` | The area window holds no whole pixel count. |
| `NO_PARTICLES` | Nothing passes the threshold and filters. The fault reports `thresholdPixels` and `rejected` counts. |
| `INTERPRETER_NOT_FOUND` | Configure Java (`imagej`) and `ij.jar` (`imagejJar`). |
| `UNSUPPORTED_RUNTIME` | The JAR is not ImageJ 1.54, or Java is older than 11. |
| `VERIFICATION_FAILED` | Evidence or native output disagrees. Keep the directory for diagnosis and run a fresh attempt. |

Image validation happens before ImageJ starts. A failed attempt keeps
`result.json` with the structured fault.

## Limits

- `analyzeParticles`: one grayscale plane per run. No colour, stacks or
  hyperstacks. `measureRegions` takes 2-8 separately captured planes and
  rectangles only: no colour, stacks, tracking, registration, non-rectangular
  selections, overlays or macros.
- Manual threshold only. No perimeter, circularity, ellipse, Feret or other
  shape descriptors.
- Pixel-count area and pixel-centre centroids are discrete measurements. They
  are not sub-pixel boundary estimates or segmentation-quality guarantees.
- Native acceptance uses synthetic targets only. It establishes the stated
  semantics on those analytic shapes, not suitability for any specific
  scientific dataset.
- Serial, single-process execution only. No live editing, native inspection or
  native project save.

## Maintenance

`upstream.json` records the absorbed release and the acceptance recipe. ImageJ
releases have letter suffixes (`1.54t`) that the shared numeric release parser
does not read. The source is therefore checked by hand: read the first entry of
`https://wsr.imagej.net/jars/list.txt` and the
[release notes](https://imagej.net/ij/source/release-notes.html). Ignore daily
builds such as `1.54u8`.

Public API references:
[ParticleAnalyzer](https://imagej.net/ij/developer/api/ij/ij/plugin/filter/ParticleAnalyzer.html),
[Calibration](https://imagej.net/ij/developer/api/ij/ij/measure/Calibration.html),
[ImageStatistics](https://imagej.net/ij/developer/api/ij/ij/process/ImageStatistics.html),
[PGM_Reader](https://imagej.net/ij/developer/api/ij/ij/plugin/PGM_Reader.html),
[Opener](https://imagej.net/ij/developer/api/ij/ij/io/Opener.html),
[ImageStack](https://imagej.net/ij/developer/api/ij/ij/ImageStack.html),
[ImagePlus](https://imagej.net/ij/developer/api/ij/ij/ImagePlus.html),
[Roi](https://imagej.net/ij/developer/api/ij/ij/gui/Roi.html) and the
[Analyze menu guide](https://imagej.net/ij/docs/menus/analyze.html).

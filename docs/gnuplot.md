# Gnuplot numeric scientific plots

The `schemaxis.gnuplot/1` document declares a useful scientific plot directly:
local numeric CSV, named columns with units, mapped series, explicit axis bounds
and optional symmetric y uncertainty or an asserted asymmetric lower/upper range envelope. Gnuplot renders SVG and PNG in its own
process. The run also retains the captured CSV and an editable trusted `plot.gp`.
The host requires Python 3.10+ and no third-party Python packages.

## Run a calibration plot

Start with [the calibration example](../examples/schemaxis/gnuplot-calibration.json).
Replace `source` with the absolute path to
[calibration.csv](../examples/schemaxis/fixtures/gnuplot/calibration.csv), then run:

```sh
schemaxis plan calibration.json
schemaxis run calibration.json --gnuplot /absolute/path/to/gnuplot --output-directory results/calibration
schemaxis verify results/calibration
```

Gnuplot needs the `svg` and libgd `png` terminals. Configure its executable through
`schemaxis configure` or pass `--gnuplot`; the integration does not alter PATH.
The supported native basis is Gnuplot 6.0.5, the July 2026 stable release, checked
against the [official homepage](https://gnuplot.sourceforge.net/) and
[release notes](https://gnuplot.sourceforge.net/ReleaseNotes_6_0_5.html).

The CSV header must exactly equal the ordered `columns[].name` values. Column
names are distinct ASCII identifiers, up to 40 characters. Every data cell is a
finite ASCII number, without surrounding whitespace. Allow 2–2048 rows, 2–12
columns, and at most 1 MiB. Missing values, dates, NaN, infinity and expressions
are rejected. Each series requires strictly increasing x values.

```json
{
  "version": "schemaxis.gnuplot/1",
  "operation": "plot",
  "title": "Sensor calibration",
  "source": "/absolute/path/calibration.csv",
  "columns": [
    {"name": "time", "unit": "s"},
    {"name": "reading", "unit": "V"},
    {"name": "uncertainty", "unit": "V"}
  ],
  "series": [{"label": "Measured", "x": "time", "y": "reading", "error": "uncertainty", "colour": "red"}],
  "xAxis": {"label": "Time", "unit": "s", "range": [0, 2]},
  "yAxis": {"label": "Reading", "unit": "V", "range": [0, 4]}
}
```

## Series, units and uncertainty

Declare 1–4 series with distinct labels and colours (`red`, `blue`, `green`,
`purple`). Omitted colour selects red, so select another colour for additional
series. Each series maps `x` and `y` to named numeric columns. All x-column units
must equal `xAxis.unit`; all y and uncertainty units must equal `yAxis.unit`.
Use `1` for dimensionless data. Units are asserted text, with no automatic
conversion or dimensional inference. The visible axes include units; legends
identify each named series.

Optional `error` maps a nonnegative **absolute symmetric y uncertainty** column.
A value `dy` draws endpoints `y-dy` and `y+dy`. These are asserted intervals;
Schemaxis does not assign a confidence level, fit a model, or infer uncertainty.
Omitting `error` draws connected circular samples without error bars.

The [changed example](../examples/schemaxis/gnuplot-calibration-variant.json)
uses [changed data](../examples/schemaxis/fixtures/gnuplot/calibration-variant.csv)
and a blue reference series. Overlapping series can obscure their raster pixels;
choose distinguishable data/colours or independent pixel verification may reject
an ambiguous plot.

## Asymmetric range envelope

Use `bounds` when a series has an **asserted lower and upper range** that is not
symmetric about the central value, for example a reported minimum and maximum, or an
interval another tool already computed. Declare three distinct numeric columns, all in
the y-axis unit:

```json
"series": [{"label": "Mean", "x": "time", "y": "mean",
            "bounds": {"lower": "lower", "upper": "upper"}, "colour": "red"}]
```

See [the envelope example](../examples/schemaxis/gnuplot-band.json),
[its changed-bounds variant](../examples/schemaxis/gnuplot-band-variant.json) and
[the CSV](../examples/schemaxis/fixtures/gnuplot/band.csv). The native plot is Gnuplot
6.0.5's released three-column `filledcurves` form (`using x:lower:upper`) at a fixed
20 percent opacity with no border, plus the central `y` curve and its markers.

**What is drawn.** A shaded polygon joins `(x, lower)` for every row, left to right, to
`(x, upper)`, right to left, with straight segments. Between rows the shading is
simple piecewise-linear interpolation for display; it asserts nothing about values
between your samples. **What it is not.** Schemaxis computes no quantile,
distribution, confidence level, simultaneous coverage, reliability or model validity.
The envelope is exactly the bounds you supplied.

**Point interval or range envelope?** Use `error` for a symmetric absolute interval
`y-dy..y+dy` at each row, drawn as separate error bars; use `bounds` for an
asymmetric or reported range drawn as a continuous shaded band. A series cannot have
both, and a series with neither is plain points. The data are never combined or
altered to make one look like the other.

Requirements, all checked before Gnuplot starts and never repaired: every cell finite;
`lower < upper` and `lower <= y <= upper` in every row; x strictly increasing; every
bound and sample inside the explicit axis ranges (no autoscale or clipping); `y`,
`lower` and `upper` are distinct columns whose units equal the y-axis unit; linear
axes only; and the envelope is the only series of its plot, so overlapping envelopes
cannot hide each other. Each row's envelope must be at least 24 pixels tall and
consecutive x samples at least 16 pixels apart (the first and last at least 26), and
every row and segment midpoint needs an interior pixel clear of the polygon boundary and
central curve. Gnuplot mirrors tick marks up to 9 pixels in from every border, so every
probe, interior or exterior, is also kept at least 12 pixels from all four borders, and at
least one exterior probe must exist; otherwise `PLOT_BAND_UNVERIFIABLE` is raised before
Gnuplot starts (the message names the row, or says that no exterior pixel can be observed,
for example when the envelope spans almost the whole y range). This is a deliberate
precision limit, not a claim that every geometry is supported: a thinner, steeper or
near-full-height envelope can be drawn by Gnuplot but not independently confirmed by
pixels, so it is refused rather than accepted with false confidence.

## Axes and logarithmic data

Each axis requires an explicit finite increasing `range`; there is no autoscale
or clipping. Ranges must contain all samples and uncertainty endpoints. Bounds
must be separated by more than 1e-10 relative to their magnitude; numeric
magnitudes cannot exceed 1e100. `scale` defaults to `linear`; `log10` selects a
base-10 logarithmic transform. All log bounds, values and uncertainty endpoints
must be strictly positive. Intervals retain their absolute `y-dy`/`y+dy` meaning
before transformation, so their displayed logarithmic lengths are asymmetric.

The [log example](../examples/schemaxis/gnuplot-logarithmic.json) and
[variant](../examples/schemaxis/gnuplot-logarithmic-variant.json) exercise real log
axes with uncertainty. The [invalid range](../examples/schemaxis/gnuplot-range-invalid.json)
sets a logarithmic bound to zero and fails before native execution.

## Verification and retained outputs

`plot.svg` and `plot.png` are raw native outputs. `plot-summary.json` is an
adaptor-authored record of independent host inspection, not native API readback.
The verifier parses SVG labels, series membership, sample markers, connecting
segments and uncertainty endpoints against the **captured numeric CSV** and
independent affine/log transforms. Fixed screen margins are 15–95 percent across
and 20–90 percent upward. At 800×600, baseline points are literally
`(120,375)`, `(440,270)`, `(760,165)`; SVG rounds by approximately .01 pixel.
The geometry tolerance is .06 pixel. For an envelope, the verifier requires exactly the
expected polygon vertices in order (lower edge left to right, then upper edge right to
left), the series fill colour, opacity `0.200000`, the legend swatch and the central
curve. Every polygon in the whole SVG must be one of exactly two, the legend swatch and the
envelope, in the first series group; an extra filled polygon anywhere else, including
the central-curve group, is refused. The swatch must be the native key sample box
(42.56 by 9 pixels) at the fixed offset from its label, so a resized or moved swatch is
refused. The verifier also probes PNG pixels inside the fill at every row and segment midpoint
(the 20 percent blend of the series colour over white). Exterior pixels are probed
where observable, with at least one exterior probe required across the plot. The SVG
vertex checks cover every bound; PNG checking remains selected visible probes. PNG is independently reconstructed from
CRC-checked chunks and all five PNG filters; dimensions and colour-bearing sample,
interval and connecting-segment pixels must agree within a 3-pixel neighbourhood.
Antialiasing is checked as a bounded blend with white. This verifies selected
scientific geometry; it does not prove full raster equivalence or typography.

The trusted script, stage input hashes, native executable/version, commands,
completion records, stdout/stderr, plans, captured bytes/digest and publication
membership are verified. Changing the original source later does not change a
retained run. Reuse hashes original source bytes, so changing those bytes at the
same path invalidates reuse. A hash is an integrity binding, not an authenticity
signature. Rewriting every input and receipt can describe a different coherent
run; the independent checks reject inconsistent or misleading native artifacts.

`plot.gp` is editable outside Schemaxis alongside `captured.csv`. An externally
edited script requires a new declared Schemaxis run to gain verified provenance.
Authored input cannot inject native commands, expressions, filenames or options.
Visible labels use ASCII letters/numbers, spaces and `._()+/-`, start with a
letter/number and cannot end with spaces. Quotes, backticks, percent, control
characters and enhanced-text syntax are excluded. Native initialisation files
are disabled using `-d`.

Both SVG and PNG default to 800×600; width is 640–1600 and height 480–1200 pixels.
The native child has a 512 MiB address-space limit, 16 MiB file limit, 60-second
CPU limit and one serial thread. One total deadline covers probes, rendering and
verification; shared cancellation terminates the owned process group. Failed runs
retain diagnostic logs and a structured fault, never a successful publication.
Shared schema storage is captured automatically at the common run boundary.

## Exporting verified runs

A run records the directory that produced it, and the receipt is never rewritten.
Copy a run with `schemaxis` export so `publication-metadata.json` records that
origin; `schemaxis verify` on the exported copy then reads every retained byte from
the selected directory and maps the recorded launcher, input and publication paths
through the origin. The captured CSV, script, SVG, PNG, summary and independent
geometry/pixel checks are still required, and an edited byte or changed digest is
refused. A directory copied by hand has no origin and is refused with
`VERIFICATION_FAILED`; its recovery says to verify the original or re-copy with
export. This is offline verification of retained bytes, not a new native render.

## Authoring and workflow reuse

Studio provides calibration, logarithmic and range-envelope starters, source editing, pointer
property edits, undo, conceptual field Help and image/text inspection. Replace
CSV placeholders before execution. Common `$document` references, pure
expressions and finite studies resolve before plotting. Workflow operations use
the same schema, plan, native execution and verification; the reusable input hook
includes captured source-byte identity. There is no native graph editor, live
Gnuplot session, reverse synchronisation, time batches or MPI execution.

This release covers connected 2D numeric series, symmetric absolute y uncertainty
and one asserted lower/upper envelope per plot on linear axes. Fitting, smoothing,
arbitrary equations/scripts, missing-data policies, unit conversion, x uncertainty,
log or multiple/overlapping envelopes, envelope opacity or style options, 3D plots, animations,
multiplots and PDF/EPS output remain outside the contract.

## Fault recovery

| Fault | Recovery |
| --- | --- |
| `INVALID_PLOT_SOURCE` | Select an absolute regular `.csv` file of at most 1 MiB; symlinks and special files are refused. |
| `INVALID_PLOT_COLUMNS` | Match distinct declared identifiers and exact CSV header order; map every series role to a declared column. |
| `INVALID_PLOT_LABEL` | Use the safe ASCII label alphabet and remove leading/trailing spaces. |
| `INVALID_PLOT_RANGE` | Use increasing separated bounds, positive for log10. |
| `PLOT_UNIT_MISMATCH` | Convert values explicitly and match every mapped column unit to its axis. |
| `INVALID_PLOT_SERIES` | Use distinct labels/colours for the bounded series. |
| `INVALID_PLOT_DATA` | Use rectangular finite numeric rows, increasing x and nonnegative absolute uncertainty. |
| `INVALID_LOG_DATA` | Ensure values and `y-dy` endpoints are positive before a log transform. |
| `PLOT_DATA_OUTSIDE_RANGE` | Expand explicit bounds to include all samples and interval endpoints. |
| `INVALID_PLOT_BOUNDS` | Use three distinct columns with `lower < upper` and `lower <= y <= upper` in every row; do not combine `bounds` with `error`. |
| `PLOT_BOUNDS_UNSUPPORTED` | Use linear axes and make the envelope the only series of the plot. |
| `PLOT_BAND_UNVERIFIABLE` | Widen the envelope to at least 24 pixels, flatten steep segments or rescale the y range so every row and midpoint has a verifiable interior, with at least one observable exterior across the plot. |
| `INTERPRETER_NOT_FOUND` | Configure an absolute executable supporting SVG and libgd PNG. |
| `RUNNER_TIMED_OUT` / `RUNNER_CANCELLED` | Inspect retained logs and failed result; retry in a fresh directory with appropriate bounded timeout. |
| `VERIFICATION_FAILED` | Retain the failed run for diagnosis; restore intact evidence or render a fresh run. Do not edit receipts to declare success. For a hand-moved or hand-copied run, verify the original directory or copy it with `schemaxis` export. |

Public mapping uses [plot](https://gnuplot.sourceforge.net/docs_6.0/loc8145.html),
[using](https://gnuplot.sourceforge.net/docs_6.0/loc9562.html),
[logscale](https://gnuplot.sourceforge.net/docs_6.0/loc13689.html),
[SVG](https://gnuplot.sourceforge.net/docs_6.0/loc22928.html) and
[PNG](https://gnuplot.sourceforge.net/docs_6.0/loc22106.html). Requalification is required when
native output structures change. Run `tools/qualify_gnuplot.py` for the bounded
acceptance, lifecycle, hostile-evidence, source-invalidation and composition cases.

## Workflow CSV handoff

The route accepts a verified workflow artifact of kind `table` or `file` as `source`, for
example `{"$artifact": "profile", "index": 1}` for the xarray `profile.csv` (see
[xarray](xarray.md#gnuplot-handoff)) or `{"$artifact": "prepare", "index": 2}` for an Apache Arrow
`publishCSV` table (see [the workflow](../examples/schemaxis/apachearrow-gnuplot-band-workflow.json)).
A kind label alone does not establish a CSV: the producer's bytes are captured exactly
and must pass the same closed numeric-CSV contract as a path source (a `.csv` path, header,
finite numeric cells, bounds) before Gnuplot starts; other files, such as Parquet, and
missing artifact indexes are refused. A CSV carries no schema or units, so the plot
document declares the columns and asserts their units; nothing is converted. Changing the
bytes of the original source at the same path invalidates both producer and consumer on
resume; an unchanged workflow reuses both after verification. Changing the authored consumer
intent needs a fresh workflow because the resume contract requires the unchanged authored
document.

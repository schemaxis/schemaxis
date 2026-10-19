# Gnuplot numeric scientific plots

The `schemaxis.gnuplot/1` document declares a useful scientific plot directly:
local numeric CSV, named columns with units, mapped series, explicit axis bounds
and optional symmetric y uncertainty. Gnuplot renders SVG and PNG in its own
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
The geometry tolerance is .06 pixel. PNG is independently reconstructed from
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

## Authoring and workflow reuse

Studio provides calibration and logarithmic starters, source editing, pointer
property edits, undo, conceptual field Help and image/text inspection. Replace
CSV placeholders before execution. Common `$document` references, pure
expressions and finite studies resolve before plotting. Workflow operations use
the same schema, plan, native execution and verification; the reusable input hook
includes captured source-byte identity. There is no native graph editor, live
Gnuplot session, reverse synchronisation, time batches or MPI execution.

This first release covers connected 2D numeric series and symmetric absolute y
uncertainty. Fitting, smoothing, arbitrary equations/scripts, missing-data
policies, unit conversion, asymmetric/x uncertainty, 3D plots, animations,
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
| `INTERPRETER_NOT_FOUND` | Configure an absolute executable supporting SVG and libgd PNG. |
| `RUNNER_TIMED_OUT` / `RUNNER_CANCELLED` | Inspect retained logs and failed result; retry in a fresh directory with appropriate bounded timeout. |
| `VERIFICATION_FAILED` | Retain the failed run for diagnosis; restore intact evidence or render a fresh run. Do not edit receipts to declare success. |

Public mapping uses [plot](https://gnuplot.sourceforge.net/docs_6.0/loc8145.html),
[using](https://gnuplot.sourceforge.net/docs_6.0/loc9562.html),
[logscale](https://gnuplot.sourceforge.net/docs_6.0/loc13689.html),
[SVG](https://gnuplot.sourceforge.net/docs_6.0/loc22928.html) and
[PNG](https://gnuplot.sourceforge.net/docs_6.0/loc22106.html). Requalification is required when
native output structures change. Run `tools/qualify_gnuplot.py` for the bounded
acceptance, lifecycle, hostile-evidence, source-invalidation and composition cases.

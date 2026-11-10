# Gnuplot asserted range envelope and CSV file handoff, 26 October 2026

Scope: `schemaxis.gnuplot/1` gains an optional series `bounds` (`lower`, `upper`), an
asymmetric asserted range envelope on linear axes, and accepts a verified workflow `file`
artifact (in addition to `table`) as the CSV `source`. Legacy points, symmetric `error`,
logarithmic and mixed cases are unchanged. This note covers only that change; it does not
re-review unrelated Gnuplot behaviour.

## What the envelope means

A shaded piecewise-linear polygon joins the asserted lower and upper columns, drawn with
Gnuplot 6.0.5's released three-column `filledcurves` form at a fixed 20 percent opacity,
behind the central `y` curve. It computes no quantile, distribution, confidence level,
simultaneous coverage, reliability or model validity. Interpolation between rows is display
only. `bounds` and `error` are mutually exclusive.

## Checklist

| ID | Result |
| --- | --- |
| registration | Route unchanged; `acceptedArtifacts` is now `table` and `file`; readiness declares an input contract for each kind. |
| schema | `series[].bounds.{lower,upper}` in the declarations, authored/expanded schemas and generated reference. |
| semantics | Refused before Gnuplot starts with exact codes and locations: `INVALID_PLOT_BOUNDS` (both `error` and `bounds`, shared columns, `lower <= y <= upper`, `lower < upper`), `PLOT_BOUNDS_UNSUPPORTED` (log axis, more than one series), `PLOT_UNIT_MISMATCH`, `PLOT_DATA_OUTSIDE_RANGE`, `PLOT_BAND_UNVERIFIABLE`, plus the existing numeric CSV faults. Nothing is clipped, sorted, imputed or autoscaled. |
| native-mapping | `plot using x:lower:upper with filledcurves` plus `using x:y with linespoints`, `set style fill transparent solid 0.2 noborder`, from the released 6.0.5 documentation. Labels remain escaped data; no authored script, expression or extra flag. |
| execution | Trusted script, source capture, stage input bindings, deadline and cancellation are unchanged. The verifier reads back every expected native polygon vertex in order, fill colour, opacity, the legend swatch (native key-sample size, at its fixed offset from the label) and the central curve, requires every polygon in the whole SVG to be one of exactly two in the envelope group, and probes PNG interior pixels at every row and segment midpoint, and exterior pixels where observable (at least one exterior probe across the plot). |
| discovery | Operation keywords, purpose and four search cases (three positive, one negative for confidence-interval estimation). |
| guidance | New records for `bounds`, `bounds.lower`, `bounds.upper`, plus the operation, series, `error`, `y` and `source` records; the shared workflow wrapper record for Gnuplot is updated. |
| help | Reference, Help topics and the guide section are regenerated and their `--check` modes pass. |
| examples | `gnuplot-band.json` and `gnuplot-band-variant.json` baseline/variant, two invalid examples, a Studio `range-envelope` starter, and `apachearrow-gnuplot-band-workflow.json`. |
| tests | `tests/unit/test_gnuplot_band.py` (host; verifier mutations run on a retained native SVG/PNG pair with literal expectations) and the existing Gnuplot, readiness, guidance, assessment, Help and Studio suites. |
| qualification | `tools/qualify_gnuplot.py` and the dedicated `tools/qualify_gnuplot_band.py`; the kit gains `range-envelope` and `changed-range-envelope`. Receipts are not registered here. |
| maintenance | `assessment.json` and `upstream.json` are not edited. The generated assessment index reports the Gnuplot record stale until it is reviewed; no score is changed. |

## Precision limits

The envelope must be at least 24 pixels tall at each row, consecutive x samples at least
16 pixels apart, and every row and segment midpoint needs an interior probe at least 3
pixels from the polygon boundary and 6 pixels from the central curve. Gnuplot mirrors tick
marks up to 9 pixels inward from every border, so every probe is also kept at least 12 pixels
from all four borders (the first and last rows are probed 13 pixels inside, so those segments
must be at least 26 pixels long), and at least one exterior probe must exist. A thinner,
steeper or near-full-height envelope can be drawn but cannot be confirmed by pixels, so it is
refused before Gnuplot starts; this does not claim that every geometry is supported. The PNG
check uses selected probes, not raster equivalence: fill removed or added between probes is
not detected. One envelope per
plot, linear axes only. Typography and whole-raster equivalence are not certified.

## Native and workflow checks

The dedicated qualifier runs actual Gnuplot 6.0.5 for the six kit cases; literal polygon
vertices and PNG samples for baseline and changed non-adjacent bounds; hostile mutations
with every digest and publication record refreshed (wrong lower/upper vertex, extra vertex,
missing or extra polygon, a nearly plot-sized extra filled polygon placed in the central-curve
group, at canvas level, nested in the fill group or in the envelope group, a resized or moved
legend swatch, wrong colour or opacity, changed plot kind, wrong curve, wrong units, fill
removed on one side only, filled exterior, changed source bounds); native geometry runs at
800x600 (with data whose upper bound lies near the top border), 640x480, 1600x1200, 1600x480
and 640x1200, each read with literal expectations and the qualifier's own PNG decoder; native oracle
runs for colour, swapped column order, an axis-edge bound, a thin envelope and a degenerate
envelope; refusal before launch for bad bounds, headers, missing cells and unsorted x; and a
timeout and a cancellation of a real Gnuplot process held by its own `pause` command in the
render stage (a stage hold, not a mid-render proof). The real workflow passes an Apache Arrow
`publishCSV` artifact (index 2, kind `file`) to the envelope: the producer CSV equals the
consumer capture, an unchanged resume reuses both, changed source bytes at the same path
invalidate both, and a changed authored consumer needs a fresh workflow because resume
requires the unchanged authored document. A missing CSV opt-in, wrong index, Parquet file,
text report, wrong header order, wrong units, out-of-range or inverted bounds are refused
before Gnuplot starts.

Commands: `PYTHONPATH=src python3 tools/qualify_gnuplot.py --gnuplot GNUPLOT
--output-directory DIR` and `PYTHONPATH=src python3 tools/qualify_gnuplot_band.py --gnuplot
GNUPLOT --apachearrow ARROW_PYTHON --output-directory DIR`.

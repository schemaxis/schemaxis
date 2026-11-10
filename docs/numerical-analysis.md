# Numerical analysis and spreadsheet workflows

This guide covers GNU Octave for real-valued 1D analysis and LibreOffice Calc for
editable spreadsheets with verified formulas. [R regression](r.md) additionally
provides independently checked numeric linear models and finite fit requirements.
They run in isolated native processes. The host Python package remains dependency-free.
Recorded bounded qualification versions include Octave 11.3.0, LibreOffice 26.8.1.1 and R 4.6.1;
readiness reports whether each receipt matches the current source.
The original Octave/Calc workflow receipt below used LibreOffice 26.8.0.3.

## Install and run

Install the applications from [GNU Octave](https://octave.org/download) and
[LibreOffice](https://www.libreoffice.org/download/), then record their executables
in your ignored personal configuration:

```bash
schemaxis configure octave /path/to/octave-cli
schemaxis configure calc /path/to/soffice
schemaxis plan examples/schemaxis/analysis/octave-signal.json
schemaxis run examples/schemaxis/analysis/octave-signal.json --output-directory signal-run
schemaxis verify signal-run
schemaxis run examples/schemaxis/analysis/calc-summary.json --output-directory workbook-run
schemaxis verify workbook-run
```

The flags `--octave` and `--calc` override configuration. Environment fallbacks are
`SCHEMAXIS_OCTAVE` and `SCHEMAXIS_CALC`; PATH lookup is the final fallback. Python
workflow callers pass `locations={'octave': executable, 'calc': executable}`.
Use fresh output directories; workflow retries use the existing `--resume` mechanism.

## Octave contract

Use `version: schemaxis.octave/1`, an ordered `nodes` array, and `outputs` naming
the tables to publish. Each node has `id`, `filter`, `options`, and, for processing
operations, `inputs: {"input": "earlierNode"}`. There are eleven operations:

| Operation | Behaviour |
| --- | --- |
| `samples` | Literal equal-length `x` and `y` vectors |
| `readCSV` | Numeric CSV with named `xColumn`/`yColumn`; absolute file path |
| `sequence` | Inclusive, evenly spaced `start` to `stop`; x equals y |
| `wave` | Sine/cosine samples; start, step, count, amplitude, frequency, phase and offset |
| `scale` | Multiply y by factor and add offset |
| `resample` | Linear interpolation to an evenly spaced x grid spanning the original endpoints |
| `movingMean` | Odd centred window; shrink at endpoints |
| `derivative` | Centred secant slope, with one-sided endpoint slopes; supports nonuniform x |
| `integral` | Cumulative trapezoidal integration with an initial value |
| `linearFit` | Least-squares line; slope, intercept and residual sum of squares in native evidence |
| `fft` | One-sided amplitude spectrum, including DC and Nyquist; frequency replaces x |

Frequency is cycles per x unit; phase is radians. No implicit physical-unit
conversion occurs. Derivatives, integrals and resampling require strictly increasing x. FFT needs
uniform sampling and 4–8192 points in a power of two. An odd smoothing window cannot
exceed the sample count. Fits need nondegenerate x variation. Literal-data nodes are
checked during planning; CSV-dependent nodes are checked at run time without
reading files during planning. See [planning checks and recovery](octave.md).

Each table has 2–10000 samples. There are at most 64 nodes and 100000 intermediate
samples in one run. Real finite values are bounded to ±1e100. These bounds prevent
unbounded authored input; they do not guarantee every ill-conditioned numerical
problem will pass verification. Results outside the independent numeric tolerance
fail explicitly. Default verification uses relative tolerance `2e-8` and absolute
tolerance `2e-9`; choose units and scaling accordingly for very small measurements.
Complex numbers, missing values, multidimensional arrays, plotting,
user functions, packages and arbitrary MATLAB/Octave expressions are not exposed.

Published artifacts are `<output-id>.csv` files in authored output order, followed
by `statistics.json`. Statistics include count, mean, median, sample standard
deviation, extrema and RMS. `native.json` also retains every intermediate table and
fit/FFT metadata. Native operations use Octave's numerical functions; verification
recomputes results with independent host algorithms, including a radix-2 FFT.

## Calc contract

Use `version: schemaxis.calc/1` and exactly one node: `fromRows` with `columns` and
`rows`, or `readCSV` with an absolute `file`. Tables that mix text IDs or notes with
measurements, or have missing values, use `fromTypedRows` or `readTypedCSV` instead; see
[typed labelled tables](calc.md#typed-labelled-tables). The numeric operations below are
unchanged. Tables have 2–10000 rows and 1–64
unique, nonempty column names. All data cells must be finite real numbers. Header
text is written as literal text, including text starting with `=`.

Every workbook contains:

- **Data:** the original table with headers.
- **Summary:** COUNT, SUM, AVERAGE, MIN, MAX and sample STDEV formulas for each column.

The trusted input ODS has no cached formula answers. Native Calc calculates an XLSX,
then a fresh process reopens that XLSX and saves an ODS. Both files must preserve
all values and the fixed formulas, with independently checked cached results.
Each native stage gets a private user profile; it does not attach to your existing
LibreOffice session. There is a shared timeout across all stages.

Optional named cell bounds and weighted reconciliations assess those observed
values independently in both formats. Unmet requirements retain their assessment
and block successful publication, consumers and reuse. See the
[complete Calc contract](calc.md) and [balanced example](../examples/schemaxis/calc-balance.json).

Artifacts are always ordered `analysis.xlsx`, `analysis.ods`, `data.csv`. The CSV
is a verified, lossless numeric interchange copy; it is not a readback of arbitrary
user-edited workbooks. Macro execution, arbitrary formulas, existing workbook import,
format preservation, charts and live spreadsheet editing are outside this first contract.

The XLSX file can be opened by Excel, OnlyOffice and other compatible tools. This
is file interchange, not native qualification of those applications. Google Sheets,
MATLAB and SYSTAT do not yet have direct adaptors. R has its own bounded
[regression contract](r.md), including a checked numeric-table handoff to Calc.

## Connect analysis, spreadsheets and geometry

```bash
schemaxis run examples/schemaxis/analysis/octave-to-calc.json --output-directory analysis-roundtrip
schemaxis verify analysis-roundtrip
schemaxis run examples/schemaxis/analysis/octave-to-blender.json --output-directory data-curve
schemaxis verify data-curve
```

The first workflow generates a signal and spectrum, sends the spectrum to Calc,
and imports the published numeric table back into Octave. The second uses Blender's
`curveFromCSV` to turn the sampled waveform into a capped 3D tube, render it and
publish an editable scene plus STL. Select the producer's CSV with a normal
`$artifact` reference; artifact indices follow the orders documented above.

## Bring an existing 1D tool

An initial integration only needs a UTF-8 numeric CSV with a header, for example:

```csv
x,y
0,1
0.25,1.5
0.5,2
```

Use an absolute CSV path in `readCSV`, or `curveFromCSV` for Blender. Extra columns
are allowed; name the required columns explicitly. Input and published CSV files
are limited to 8 MiB. Calc checks the publication size before launching its native
process. Spreadsheet XML entries are bounded to 128 MiB, accommodating native ODS
output for the maximum 10000 × 64 table.
The adaptors retain input bytes and hashes, and scheduler reuse checks source hashes.
A changed source causes a fresh execution rather than reuse of stale results.
Blender curves are limited to 1024 points; optional `zColumn` supplies 3D coordinates,
otherwise z is zero. CSV coordinates use Blender's native units with no inferred scale.

A direct adaptor for a specific 1D creator should add a bounded input contract,
its native command/IPC integration, and independent checks of the resulting table.
The CSV bridge allows those tools to participate before such an adaptor exists.

## Qualification

```bash
PYTHONPATH=src python3 tools/qualify_analysis.py \
  --octave /path/to/octave-cli --calc /path/to/soffice \
  --blender /path/to/blender --output-directory evidence/analysis-new
```

The native unit checks additionally use `SCHEMAXIS_TEST_OCTAVE` and
`SCHEMAXIS_TEST_CALC`. Run `tests/unit/test_numeric_analysis.py` through unittest
discovery with both set to require zero native skips. See the
[retained qualification summary](../verification/2026-09-25-adaptor-expansion.json).

## Development admission

This adaptor now provides the [development kit](adaptor-development.md) delivery
contract, operation selection guidance, explicit optional-feature decisions and
an editable [acceptance example](../examples/schemaxis/calc-admission.json).
Run the common host/native conformance recipe and inspect its scoped source-bound
receipt; structural admission alone is not native qualification. The
[current audit](design/adaptor-framework/AUDIT.md) records native availability and
exact qualification limits.

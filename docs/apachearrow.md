# Apache Arrow nullable table interchange

Use `schemaxis.apachearrow/1` with `operation: prepareTable` to turn an explicitly
typed CSV table into portable Parquet and an inspectable JSON report. Filter source
rows, select/reorder and rename columns, widen int32 to int64, and replace nulls only
when explicitly requested. Source row order is preserved. This route complements
SQLite relational summaries with Unicode, wide identifiers, floating-point and UTC
timestamp interchange. It does not execute SQL or infer a schema.

The native target is PyArrow **26.0.0**, with Arrow C++ **26.0.0**, in an isolated
Python 3.11+ environment on POSIX. Schemaxis discovery, planning and verification
use only the Python 3.10+ standard library. Install the native package separately;
do not add PyArrow to the host environment. Configure that environment's absolute
Python executable or supply `--apachearrow /absolute/venv/bin/python`.

## Start with measurements

Edit [the baseline](../examples/schemaxis/apachearrow-measurements.json), replacing
`source` with the absolute path to
[measurements.csv](../examples/schemaxis/fixtures/apachearrow/measurements.csv).

```sh
schemaxis plan measurements.json
schemaxis run measurements.json --apachearrow /absolute/venv/bin/python --output-directory fresh-table
schemaxis verify fresh-table
```

The example preserves int64 extrema and an identifier above 2^53, negative zero,
Unicode text, empty strings, missing values and pre-epoch/leap-day timestamps.
[The selection example](../examples/schemaxis/apachearrow-selection.json) keeps
enabled rows, selects label/batch/time and widens the batch integer. The
[empty example](../examples/schemaxis/apachearrow-empty.json) retains a typed schema
with zero rows; the [null-row example](../examples/schemaxis/apachearrow-null-row.json)
selects a missing timestamp. [The invalid cast](../examples/schemaxis/apachearrow-cast-invalid.json)
demonstrates rejection of an unsupported conversion. Studio has editable baseline
and selection starters, including nested field Help.

## CSV contract and types

Declare every column in header order. Source names and output names are unique
lower-case ASCII identifiers: a letter followed by letters, digits or underscores,
at most 40 characters. Column names are identifiers, not expressions.

The source is a regular local `.csv` file, not a URL, directory, wildcard or file
symlink. It is UTF-8 without BOM, comma-delimited, with an exact first-row header.
Double quotes enclose complete cells and doubled quotes escape a quote. Records use
LF or CRLF; quoted embedded newlines are preserved. Spaces are significant. No
comments, skipped lines, missing/extra cells or NUL characters are accepted.

The cell `\N` alone means null, whether quoted or unquoted. Empty text remains empty;
`NA`, `None` and `null` remain text. A literal nonnull `\N` cannot be represented.
An empty numeric, boolean or timestamp cell is invalid. `nullable` defaults to false.
Every source cell is validated, including rows later filtered out.

| Type | Meaning and accepted spelling |
|---|---|
| `bool` | Exactly `true` or `false`; neither 0/1 nor case variants. |
| `int32` | Signed 32-bit base-ten integer. |
| `int64` | Signed 64-bit base-ten integer, parsed without float conversion. |
| `float64` | JSON-number decimal syntax, rounded to finite IEEE binary64; preserves signed zero. |
| `utf8` | Unicode text with original case, whitespace and code points; no normalisation. |
| `timestamp_us_utc` | Valid `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` or `+00:00`, with 1–6 fractional digits when present. |

Integers reject plus signs, whitespace, leading zeroes and negative zero. Doubles
reject nonfinite values, overflow and nonzero underflow to zero. Decimal rounding
to binary64 is intentional; this is not decimal-exact arithmetic. Native parsing is
checked against the independent host parser, including exact floating-point bits.

Timestamps use four-digit Gregorian years 0001–9999. Naive timestamps, nonzero UTC
offsets, named zones, leap seconds and extra fractional digits are rejected. Epoch
microseconds are exact integers; native local timezone settings do not participate.
Z/+00:00 spelling is normalised, not preserved as metadata.

## Selection, filters and missing values

`where` is an optional list of up to eight predicates; every predicate must pass.
Each names a source `column`, a `test`, and a lexical string `value` for comparisons.
Using text for literals avoids JSON/Studio rounding of wide integers. The value
must have the same spelling rules as that source column.

Numeric and timestamp comparisons support `eq`, `ne`, `lt`, `le`, `gt`, `ge`.
Boolean and text columns support only `eq`/`ne`. `isNull` and `isValid` work on any
column and omit `value`. A comparison involving null drops the row, including `ne`.
Filters run on source values before selection, casting or replacement.

`select` is a nonempty ordered list of distinct source `column` and output `name`
pairs. Omitted source columns are deliberately excluded from the output.
`cast: "int64"` is supported only for an int32 source; narrowing, float conversions,
string conversions and timestamp conversions are not supported.

`fillNull` is optional on nullable sources. It is a nonnull lexical string parsed
as the selected output type, after any widening. It changes only nulls and marks
the output field nonnullable. Without replacement, the declared nullability is
retained even if this particular result contains no null cells. Supplying fillNull
on a nonnullable source is an error, not a silent no-op.

## Outputs and workflow handoffs

Publication order is fixed: **0** `table.parquet` (file), **1** `table-report.json`
(text). Parquet stores exact physical types, nullability, UTF8 and UTC-microsecond
logical types. It is uncompressed PLAIN with v1 data pages and no dictionary,
statistics-based filtering, partitioning, encryption or Arrow schema metadata.

The report contains the captured source hash, input/output row counts, selected
zero-based source row indices, output column declarations, null counts and all rows.
Int64 values are decimal strings; timestamps are canonical UTC strings with six
fractional digits. Other types use normal JSON boolean/int32/double/text/null values.
This protects wide identifiers from JavaScript rounding. A generic JSON consumer
may erase the sign of zero; the Parquet verifier checks its actual float bits.

[The workflow example](../examples/schemaxis/apachearrow-sqlite-workflow.json)
hands SQLite's verified `summary.csv` artifact 2 to Arrow. The consumer declares
`g0` as nullable text, `row_count` as int64 and `total` as nullable int64. Both routes
use the same reserved null token. A verified artifact path does not eliminate the
need to declare its exact header, types and nullability. Parquet can then be opened
by an external compatible data-analysis tool; no downstream Parquet adaptor is
implied. Shared composition, expressions and finite studies also remain available.

Source byte hashes participate in workflow reuse. Editing bytes at the same path
invalidates reuse; unchanged sources can reuse a verified attempt. Standalone
verification uses the immutable retained capture and can succeed after the original
source disappears. It does not silently reread a changed external file as the old
run's input. Shared schema-store evidence is provided by the framework.

## Verification and limits

Normal verification parses Parquet with an independent standard-library reader,
compares every typed value/null position and ordered schema to a row-by-row CSV
oracle, and compares the complete report. It validates Compact-Thrift wire types,
logical annotations, definition levels, PLAIN pages and exact contiguous file
regions. External chunks, opaque schema metadata, overlapping offsets, unsupported
encodings and unused bytes fail. A fresh PyArrow reopen is additional evidence.
Successful native exit, hashes alone or native self-readback are insufficient.

Captures, authored/effective input, native worker/configuration, implementation
fingerprints, consumed-input bindings, command submissions and logs are retained.
Changed source code makes the saved verification stale and requires a new run.
Execution uses owned process groups, total timeout/cancellation and one CPU/I/O
thread; native resource caps are 2 GiB address space, 30 CPU seconds and 32 MiB
per output file. Failed attempts retain an explicit failed result.

Limits: 32 columns, 10,000 rows, 200,000 source cells, 8 MiB source/aggregate text,
4,096 UTF-8 bytes per cell, 32 MiB publication, 1 MiB footer, 4 KiB page header,
16 row groups and 20,000 pages. Fixed row groups contain at most 1,024 rows.

No authored field/schema metadata or units are accepted: `metadata`, `unit` and
`description` fields fail rather than disappearing. No unit conversion is inferred.
There are no nested/list/map/dictionary/extension/decimal/binary/date/duration types,
general Parquet inputs, SQL, joins, aggregates, arbitrary scripts, cloud datasets,
compression choices, live editing or MPI. This is a closed output verifier, not a
general-purpose Parquet validator.

`INVALID_ARROW_SOURCE` needs an absolute bounded regular CSV; `INVALID_ARROW_DATA`
identifies the row/column with a lexical, type, null or CSV problem.
`INVALID_ARROW_COLUMN`, `INVALID_ARROW_PREDICATE`, `INVALID_ARROW_SELECTION` and
`INVALID_ARROW_LITERAL` identify the authored field to correct.
`INTERPRETER_NOT_FOUND` needs the isolated native Python. Native runtime mismatch
requires installing/requalifying the supported release. `VERIFICATION_FAILED` means
retain evidence and investigate the mismatch, not relabel it verified. Timeout and
cancellation require a new output directory before retrying.

## Public API and maintenance

The implementation maps official [CSV conversion](https://arrow.apache.org/docs/python/generated/pyarrow.csv.ConvertOptions.html),
[table operations](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html),
[safe casts](https://arrow.apache.org/docs/python/generated/pyarrow.compute.cast.html)
and [Parquet writing](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_table.html).
Independent decoding follows [Parquet encoding](https://github.com/apache/parquet-format/blob/master/Encodings.md),
[logical type](https://github.com/apache/parquet-format/blob/master/LogicalTypes.md)
and [metadata definitions](https://github.com/apache/parquet-format/blob/master/src/main/thrift/parquet.thrift),
plus the [Apache Compact protocol](https://github.com/apache/thrift/blob/master/doc/specs/thrift-compact-protocol.md).
The [official release source](https://arrow.apache.org/install/) identifies latest
stable 26.0.0, released 9 October 2026. Requalification is required before advancing
the absorbed version or broadening this output subset.

Run `tools/qualify_apachearrow.py` for native semantic boundaries, malformed evidence,
lifecycle and actual SQLite handoff. See the
[completion review](../verification/2026-10-17-apachearrow-completion.md) for current
qualification status and [generated reference](generated/apachearrow-operations.md)
for the complete field schema.

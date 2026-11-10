# Calc numeric workbooks and requirements

Use `schemaxis.calc/1` to turn one finite numeric table into editable XLSX and
ODS workbooks and a checked CSV round trip. `fromRows` supplies the table in JSON;
`readCSV` imports an absolute UTF-8 numeric CSV path. Tables that also carry part or
sample IDs, notes or missing measurements use the separate
[typed labelled tables](#typed-labelled-tables) operations; the numeric operations and
their retained receipts are unchanged. Tables have 2 to 10,000
rectangular rows and 1 to 64 unique column labels. Numbers have magnitude at most
1e100; booleans and numeric strings are rejected. CSV inputs and fingerprints
read only regular files, with an 8 MiB byte limit. Header labels remain literal
text even when they begin with `=`. No authored native formula is executed.

CSV cells must be plain ASCII decimal numbers: an optional sign, digits with an
optional fraction and an optional exponent (`12`, `-3.5`, `.5`, `1.2e3`).
Surrounding spaces or tabs are ignored. Thousands separators or underscores
(`1_000`), non-ASCII digits, currency or percent signs, hexadecimal, `nan`/`inf`
and empty cells are rejected rather than reinterpreted. Labels, from either source,
cannot contain unpaired surrogates or U+FFFE/U+FFFF, which workbook XML cannot
represent. Numeric cell grammar and finite/range faults locate the record
(`rows[i][j]`, zero-based over data cells), give the CSV record number (header is
record 1), column label and offending text, and include a recovery hint. Header
labels and overall table-shape faults may instead identify a column or the table. Correct the source
and retry in a fresh output directory. Runs retained before this check still
verify against their captured CSV.

For the numeric operations, native LibreOffice Calc calculates the generated ODS, exports XLSX, then reopens
that XLSX in a second isolated headless process and exports ODS. Independent host
arithmetic checks every data value and summary cache in both formats. The
verifier also checks the exact fixed formula grammar. For the numeric operations, cache comparison uses the
existing table tolerance (relative 2e-8, absolute 2e-9); the typed operations use the
separate Data and Summary precision rules described under typed tables, and requirement
tolerances are separate and can be stricter. A requirement tests the observed native value,
not a host replacement for that value.

The **Data** sheet has headers in row 1 and numeric records from row 2. Columns
follow the authored order. The **Summary** sheet has one row per data column,
starting in row 2. Its columns are A: label, B: COUNT, C: SUM, D: AVERAGE, E: MIN,
F: MAX and G: sample STDEV. For example, the sum of the second data column is
`Summary.C3`. Counts are dimensionless; sums, means, extrema and standard
deviations retain the data column's declared units.

Optional root `requirements` contains at most 64 uniquely named checks. Names
start with an ASCII letter and contain letters, digits, `_` or `-`, up to 64
characters. Selectors use `sheet` (`Data` or `Summary`) and canonical uppercase
A1 `cell` notation. Ranges and `$` markers are rejected. The declared address
ceiling is Data.BL10001 or Summary.G65; selecting an unpopulated cell reports
`missing`. Selecting a label reports `non-numeric`, without coercion.

- `cellBounds` has one `cell` selector and at least one inclusive `minimum` or
  `maximum`. Declared bounds are finite and within ±1e100; minimum cannot exceed
  maximum. Margin is the smaller distance to any supplied bound.
- `reconcile` has 2 to 16 distinct cell `terms`, each with an explicit nonzero
  finite `coefficient` within ±1e6. The weighted sum must equal `target` (default
  zero) within the supplied nonnegative `absoluteTolerance`, at most 1e100.
  Margin is tolerance minus absolute difference from target. A zero tolerance
  requires exact equality of the observed floating-point calculation.

The author is responsible for compatible units, conversion coefficients and a
meaningful tolerance. Schemaxis does not infer unit conversions or financial,
scientific or statistical meaning from labels. `requirements.json` retains every
observed value, bound/target/tolerance, signed margin and condition separately for
XLSX and ODS. A nonnegative margin passes. `worstFormats` compares native formats
for each named requirement; it never ranks unrelated checks with different units.

[The balanced example](../examples/schemaxis/calc-balance.json) requires two
column sums to reconcile and limits the income total. For a regression table
with `sample,observed,prediction,residual`, residual extrema live at Summary.E5
and F5; a total reconciliation can combine C3 − C4 − C5. Choose the residual
bounds and tolerance from the intended model contract, not from the numbers
produced by a candidate model.

Unmet limits report `REQUIREMENTS_UNMET`. Missing, text or non-finite selected
values report `REQUIREMENT_SELECTION_FAILED`. Invalid authored addresses report
`INVALID_SELECTOR`; malformed tables report `INVALID_TABLE`. Native cache or
formula mismatches report `VERIFICATION_FAILED` independently of requirement
performance. Failed native checks retain both workbooks, logs, the assessment
and a failed result, but produce no verified publication receipt. They block
consumer jobs and cannot be reused as successful producers. Inspect the fault's
assessment and retained evidence, correct the input or declared contract, then
retry in a fresh attempt. Passing attempts are reverified, including assessment
recomputation and input fingerprints, before workflow reuse.

Artifact indices stay 0: `analysis.xlsx` (spreadsheet), 1: `analysis.ods`
(spreadsheet), 2: `data.csv` (numeric table). The assessment is retained run
evidence, not an extra handoff artifact. CSV handoffs preserve finite numeric
values and labels; workbook formatting, arbitrary formulas, external links,
macros and general workbook editing are outside this route. Only isolated
headless LibreOffice is qualified, with no Excel, OnlyOffice or Google Sheets
execution claim. Keep the full run directory for verification. Shared elapsed
native/verification deadlines and cancellation prevent final publication after
an expired or cancelled run.

## Typed labelled tables

`fromTypedRows` (JSON records) and `readTypedCSV` (a captured CSV file) keep text and
numbers in one verified, editable workbook: part or sample IDs with leading zeros,
literal notes, Unicode, and measurements that may be missing. Nothing is guessed. Every
column is declared; there is no type inference and no date, currency, time-zone or unit
handling. Put units in the column name (`Mass (g)`); Schemaxis does not convert them.

```json
{"id": "parts", "filter": "fromTypedRows", "options": {
  "columns": [{"name": "Part ID", "kind": "text"},
              {"name": "Mass (g)", "kind": "number", "nullable": true},
              {"name": "Note", "kind": "text", "nullable": true}],
  "rows": [["00123", 12.5, "=1+2"], ["00124", null, null], ["@part-7", 0, "-02"]]}}
```

### Columns, bounds and missing values

`columns` has 1 to 64 entries with a unique `name` (1 to 128 characters, no control
characters), a `kind` of `text` or `number`, and `nullable` (default `false`). A table
has 1 to 10,000 records and at most 100,000 cells. Text cells hold 1 to 1,024 characters
and at most 4 MiB in total; CSV input is limited to 8 MiB. Every record needs at least
one present cell, and every `number` column needs at least two present values because
COUNT, AVERAGE and sample STDEV are published for it.

| Value | Representation | Meaning |
| --- | --- | --- |
| JSON `null` (CSV: the null token) | blank workbook cell | Missing. Allowed only in a column declared `nullable`. |
| `0` | numeric cell `0` | A measured zero, counted by COUNT and used by SUM, AVERAGE and MIN. |
| `""` | rejected | Native ODS reopening turns empty text into a blank, so empty text could not be told from missing. Use `null`. |

Number cells are finite JSON numbers within ±1e100. Booleans, numeric strings and `NaN`
are rejected, never converted. Integer numbers beyond 2^53 are rejected, because binary64
cannot hold them exactly; declare such identifiers as text. A decimal spelling in a typed
CSV, such as `9007199254740993.0`, is not an integer lexeme: it is read as a binary64 value
and rounds to the nearest representable number, so use text for exact long identifiers. A
negative zero is stored as zero. The published `data.csv` carries the exact binary64
value; native XLSX export keeps 15 significant digits, so the workbook is verified at two
separate precisions:

| Where | Rule |
|---|---|
| Data cells, and the Summary MIN and MAX (copies of Data values) | relative 1e-14, no absolute term; text, blanks and kinds are exact. |
| Summary SUM, AVERAGE and STDEV | relative 2e-8 plus an absolute term of 1e-12 times the largest magnitude present in that column. |
| Summary COUNT and MISSING, shape, kinds, formulas, digests | exact; a fractional or boolean count is rejected. |

The absolute term scales with the column, so a column of 1e-12 to 3e-12 readings cannot
match a forged SUM of 0 or a STDEV of 1e-9, and a column whose present values are all zero
accepts only exact zero statistics. It exists to absorb summation order and cancellation
(for a column holding 1e9, 0.25 and -1e9, a SUM within about 1e-3 of 0.25 is accepted and a
SUM of 0.35 is not). The `typed-summary.json` figures use the same rule; its counts, digests
and every other field are compared exactly. The separate numeric operations keep their own
tolerance of relative 2e-8 and absolute 2e-9.

Text cells keep their exact code points: no trimming, case change or Unicode
normalization (NFC and NFD stay different), and runs of spaces are kept. A text column
rejects numbers (`123` is not `"123"`) and the reverse. Control characters (C0, DEL, C1),
U+2028/U+2029, unpaired surrogates and U+FFFE/U+FFFF are rejected with their code point
because the workbook formats cannot hold them as exact cell text. Text beginning with
`=`, `+`, `-` or `@`, such as `=1+2`, `+SUM(A1:A2)`, `-02` or `@part`, is stored as a
string cell in ODS and XLSX and in the CSV; it is never a formula. Authored formulas
remain unsupported. Opening `data.csv` in another spreadsheet may interpret those cells;
the workbooks and the CSV grammar below do not.

### Null token and typed CSV

`nullToken` (default `\N`, 1 to 16 visible characters, not a decimal number, no comma,
quote or space) marks missing cells in the CSV handoff and in `readTypedCSV` input. It is
reserved: text equal to the token is rejected, so a literal `\N` cannot be present text.
A column cannot be named with the token. The default matches the Apache Arrow adaptor's
source dialect. The declared token is authoritative: a CSV that marks missing cells with a
different marker is not reinterpreted, so that marker is ordinary text in a text column
and an `INVALID_TABLE` fault in a number column.

`readTypedCSV` requires `file` (absolute path), `columns` and optional `nullToken`. The
grammar is closed: UTF-8 without a byte-order mark, comma-delimited, LF or CRLF records,
cells either bare or wholly double-quoted with `""` for a quote. A quote inside a bare
cell, an unterminated quote, a bare carriage return, blank lines, line breaks inside
cells, trailing commas and ragged records are rejected. The first record must equal the
declared names in order. A bare or quoted token cell is missing; numbers must be plain
ASCII decimals (`12`, `-3.5`, `.5`, `1.2e3`) without spaces, separators, currency or
percent signs, and number cells are never trimmed. This does not change `readCSV`, which
still rejects the token and every blank. The file is captured byte for byte; changing its
bytes, the declared columns or the token is a different input and cannot reuse an earlier
run.

Faults are `INVALID_TABLE` with the zero-based location `rows[i][j]` (`rows[i]` for a
width error, `columns[j].name` for a header difference), and for CSV also the one-based
`record`, column `name`, source and the offending value; unknown keys, unsupported kinds
and booleans are reported by the declaration check at the same cell. `RESOURCE_LIMIT`
reports a bound.

### Workbook, summaries and requirements

The **Data** sheet has the header in row 1 and one record per row from row 2; nulls are
blank cells. The **Summary** sheet has one row per `number` column only, starting in
row 2, in declared order: A label, B COUNT, C SUM, D AVERAGE, E MIN, F MAX, G sample
STDEV and H MISSING. COUNT counts numbers; MISSING is `COUNTBLANK` over the column, so
COUNT + MISSING equals the record count; the other statistics ignore blanks. Text
columns are never summarised or used in arithmetic. `Summary.C2` is therefore the sum of
the first *number* column, which is not necessarily the second Data column. Requirements
accept Summary cells up to `H65` for these operations (`G65` for the numeric ones) and
Data cells up to `BL10001`. A blank Data cell reports `missing`, a text ID reports
`non-numeric` without coercion, and a zero is an ordinary value.

Publications keep indices 0 `analysis.xlsx`, 1 `analysis.ods` and 2 `data.csv`. For typed
operations `data.csv` is the verified typed handoff: header and text cells always quoted,
numbers as the shortest exactly round-tripping decimal, missing cells as the bare token.
It is a `table` artifact that another typed `readTypedCSV` can consume, with its own
declared columns; numeric table consumers reject it rather than guess. The run also keeps
`typed-summary.json`, bound by SHA-256 in `verification.json`: per column, the declared
kind and nullability, present and missing counts, a SHA-256 over the ordered exact values
(bound to text, Unicode, order and missingness), distinct count for text and
sum/mean/min/max/stdev for numbers.

### Verification and limits

Native LibreOffice converts the generated ODS to XLSX and the XLSX to ODS in separate
isolated processes. The verifier then reads both native files itself: every cell must have
the declared type (string, number or blank) and exact text; Summary cells must hold the
fixed formulas and recalculated caches; and no other formula, hyperlink, merged cell,
validation, data style, macro, external link, phonetic text or object may exist.
Formatting-only font runs that LibreOffice writes around unusual characters are accepted
when their joined text is exact. A
counterexample whose ordinary file hashes were refreshed still fails these semantic
checks. Retained runs, `data.csv`, `typed-summary.json`, the captured CSV, the digest
manifest, timeouts and cancellation are checked as for numeric runs.

This is LibreOffice 26.8.1.1 headless evidence only. It makes no Excel or Google Sheets
claim, and no claim about currency, clinical, financial or other domain correctness.
Formatting, styles, formulas other than the fixed Summary set, and general workbook
editing are outside the route.

### Binding a producer's CSV file

The route accepts incoming `table` and generic `file` artifacts. A producer that
publishes a regular CSV as a `file`, such as SQLite's `summary.csv`, can therefore feed
`readTypedCSV` as `"file": {"$artifact": "summary", "index": 2}`; see
`examples/schemaxis/calc-sqlite-typed-workflow.json`. The `file` kind says nothing about
content, so it does not make the bytes trusted: Calc captures the file and parses it with
the declared header, kinds and null token before any native process starts. Content that
cannot be read as that CSV stops the run with `INVALID_TABLE` and publishes no workbook,
for example SQLite's binary `summary.sqlite` bound by mistake (the fault names the
UTF-8 failure), an empty label, a padded or quoted number, a renamed header or a null in a
non-nullable column. A `text` or other kind is refused by the workflow with
`TYPE_MISMATCH`; an absent artifact index is `INVALID_SELECTION`; a producer that is not
earlier in the workflow is `UNAVAILABLE_OPERATION`. Changing the producer's input changes
the captured bytes, so the consumer reruns rather than reusing its earlier workbook.

You must declare the columns the producer writes, in order, using its own header names
(SQLite writes `g0`, `row_count` and `total` for one group column). SQLite writes NULL as
`\N` and cannot tell a stored text value `\N` from NULL, so that value would read as
missing. SQLite text is printable ASCII, so Unicode text cannot arrive through that
producer; use `fromTypedRows` or a CSV from another source for it. Row counts and totals
that SQLite writes as integers are read as exact numbers. No other producer is claimed:
an Arrow CSV publication is the Arrow adaptor's own contract; this guide makes no claim about
it beyond that any explicit CSV that matches the declared header, kinds and null token is
accepted. Evidence for that pairing belongs to the combined workflow qualification, not to
this adaptor's own acceptance.

Run the bounded native acceptance tools with a configured executable:

```sh
PYTHONPATH=src python3 tools/qualify_calc_requirements.py --executable /path/to/soffice --output-directory /fresh/evidence/calc
PYTHONPATH=src python3 tools/qualify_calc_typed.py --executable /path/to/soffice --sqlite /path/to/sqlite3 --output-directory /fresh/evidence/calc-typed
```

The tool independently reads literal XLSX and reopened ODS totals, checks exact
boundaries and explicit coefficients, alters assessments/formulas, and exercises
blocked and reused CSV workflows. It qualifies these fixtures, not all native
workbooks. The typed tool reads every native cell of the declared-row, captured-CSV,
Unicode and blank-position workbooks with its own XLSX and ODS code and hand-stated
literals, then alters native files and refreshes their ordinary hashes to show that only
the semantic checks reject them. It also exercises bad inputs, timeout, cancellation,
the verified typed handoff, reuse and its invalidation by changed bytes or documents. With
`--sqlite /path/to/sqlite3` it also runs the SQLite to Calc workflow above and reads every
native cell of the result. It
qualifies these fixtures, not all native workbooks. See LibreOffice's [Calc guide](https://help.libreoffice.org/latest/en-US/text/scalc/main0000.html)
and [formula entry guide](https://help.libreoffice.org/latest/en-US/text/scalc/guide/formulas.html)
for the native application; the bounded grammar above is the Schemaxis contract.

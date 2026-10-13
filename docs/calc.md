# Calc numeric workbooks and requirements

Use `schemaxis.calc/1` to turn one finite numeric table into editable XLSX and
ODS workbooks and a checked CSV round trip. `fromRows` supplies the table in JSON;
`readCSV` imports an absolute UTF-8 numeric CSV path. Tables have 2 to 10,000
rectangular rows and 1 to 64 unique column labels. Numbers have magnitude at most
1e100; booleans and numeric strings are rejected. CSV inputs and fingerprints
read only regular files, with an 8 MiB byte limit. Header labels remain literal
text even when they begin with `=`. No authored native formula is executed.

Native LibreOffice Calc calculates the generated ODS, exports XLSX, then reopens
that XLSX in a second isolated headless process and exports ODS. Independent host
arithmetic checks every data value and summary cache in both formats. The
verifier also checks the exact fixed formula grammar. Cache comparison uses the
existing table tolerance (relative 2e-8, absolute 2e-9); requirement tolerances are
separate and can be stricter. A requirement tests the observed native value,
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

Run the bounded native acceptance tool with a configured executable:

```sh
PYTHONPATH=src python3 tools/qualify_calc_requirements.py --executable /path/to/soffice --output-directory /fresh/evidence/calc
```

The tool independently reads literal XLSX and reopened ODS totals, checks exact
boundaries and explicit coefficients, alters assessments/formulas, and exercises
blocked and reused CSV workflows. It qualifies these fixtures, not all native
workbooks. See LibreOffice's [Calc guide](https://help.libreoffice.org/latest/en-US/text/scalc/main0000.html)
and [formula entry guide](https://help.libreoffice.org/latest/en-US/text/scalc/guide/formulas.html)
for the native application; the bounded grammar above is the Schemaxis contract.

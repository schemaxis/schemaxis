# Calc typed labelled tables

Date: 25 October 2026 (client local). Scope: the existing `schemaxis.calc/1` route.
Runtime: LibreOffice 26.8.1.1 headless, serial, one isolated process per conversion.

## What was added

- `fromTypedRows` and `readTypedCSV` read a closed typed table: every column is declared
  with a name, a kind (`text` or finite `number`) and nullability. Nothing is inferred.
  Empty text is rejected because native ODS reopening turns it into a blank; null is the
  only missing value and becomes a blank cell. Text beginning with `=`, `+`, `-` or `@`
  stays a literal string.
- The Summary sheet covers declared number columns only (COUNT, SUM, AVERAGE, MIN, MAX,
  sample STDEV, and MISSING as COUNTBLANK). Text columns never enter arithmetic.
- `data.csv` is a typed handoff with its own format, null token and loss declaration;
  `typed-summary.json` records per-column counts, missingness and exact-value digests.
- The route now accepts `file` artifacts as well as `table`. A producer's regular CSV can
  bind `readTypedCSV`; the file kind does not make the content trusted, and the CSV is
  parsed against the declared header, kinds and null token before any native process.
- `fromRows` and `readCSV` keep their numeric grammar. Retained numeric runs verify
  byte-for-byte as before.

## Evidence run on 26.8.1.1

`tools/qualify_calc_typed.py --sqlite` reads every native cell of the XLSX and the
reopened ODS with its own XML code and hand-stated literals (492 cells), then:

- checks literal expectations for leading-zero IDs, formula-looking text, Unicode
  (including NFC/NFD, non-breaking and zero-width characters, emoji), blank versus zero,
  and fixed Summary formulas and caches in both formats;
- alters native files and refreshes the ordinary hashes to show that only the semantic
  checks reject them (25 cases), and runs 13 bad-input, timeout and cancellation controls;
- runs the Calc-to-Calc typed handoff, reuse on resume, and invalidation by changed bytes
  or documents;
- runs a real SQLite 3 summary through the framework workflow: SQLite writes
  `summary.csv` as a `file` artifact, Calc binds it, the captured bytes equal the
  producer's exactly, and both native workbooks match the stated cell values and
  Summary figures. A changed SQLite source reruns the consumer; an unchanged resume
  reuses both steps. Eight controls fail with the expected structured fault: the binary
  database bound as the CSV, a `text` artifact, an absent index, an absent producer, a
  renamed header, a number kind for a label, a null in a required column and an empty
  SQLite label;
- reads two retained numeric runs read-only and confirms their bytes are unchanged.

## Limits

- SQLite text is printable ASCII, so Unicode text does not travel through that producer;
  it is covered by declared rows and typed CSV files. SQLite also cannot tell a stored text
  value equal to the null token from NULL, so that value reads as missing.
- Workbook numbers keep 15 significant digits; `data.csv` keeps the exact binary64 value.
- This note does not claim an Arrow-produced CSV has been run through the file binding;
  any explicit CSV that matches the declared header, kinds and null token is accepted, and
  the paired Arrow-to-Calc evidence belongs to the combined workflow qualification.
- No Excel or Google Sheets execution, and no claim about currency, clinical, financial or
  other domain correctness. Dates, time zones and units are not inferred.
- `absorbedVersion` is unchanged and no qualification receipt was edited.

## Repair of 26 October 2026: Summary precision

An independent review found that Summary SUM, AVERAGE, MIN, MAX and STDEV used the shared
table tolerance (relative 2e-8, absolute 2e-9) and `typed-summary.json` used an absolute
1e-12. For a column such as `[1e-12, 3e-12]`, a forged SUM of 0 or STDEV of 1e-9 was
accepted. The typed path now separates two precisions:

- Data cells and Summary MIN and MAX (copies of Data values): relative 1e-14, no absolute
  term. LibreOffice 26.8.1.1 writes 15 significant digits.
- Summary SUM, AVERAGE and STDEV: relative 2e-8 plus an absolute term of 1e-12 times the
  largest magnitude present in that column. An all-zero column (scale 0) accepts only exact
  zero statistics. Underflow-scale columns fall back to the relative term alone.
- COUNT, MISSING, shape, kinds, formulas, digests and text are exact. A fractional count, a
  boolean or an infinite or non-finite statistic is rejected.
- `typed-summary.json` uses the same rule through one shared function. The separate numeric
  operations and the shared tabular helpers are unchanged.

Evidence: host tests forge tiny-magnitude, all-zero, underflow, mixed-sign and cancelling
columns in hand-built XLSX and ODS workbooks and in `typed-summary.json` with every ordinary
digest refreshed to match; the same tests fail when the old tolerance is restored. A fresh
native run on LibreOffice 26.8.1.1 adds a tiny, an all-zero and a mixed-sign column
(594 cells read by the independent oracle, now with a column-scaled tolerance and exact counts),
plus 15 further tamper cases with refreshed hashes (40 in total). The earlier 25 October
evidence is unchanged. A decimal CSV spelling above 2^53, such as `9007199254740993.0`,
rounds to the nearest binary64 value; the integer spelling is refused. Declare long exact
identifiers as text.

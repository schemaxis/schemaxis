# Calc typed table input strengthening

Scope: existing `schemaxis.calc/1` route only. No new operation, field, native
mapping or supported format. This is a host-side admission change; the retained
native acceptance was not rerun for it and remains bound to its earlier source.

## Defects reproduced before repair

- `readCSV` parsed cells with Python `float()`, so `1_000` became 1000 and
  non-ASCII digits such as Arabic-Indic `١٢٣` became 123, silently changing
  the published table. Rejected cells (empty, `$5`, `5%`) reported location `$`
  with a raw Python message and no record, column or value.
- A `fromRows` column label containing an unpaired surrogate passed planning, then
  failed after output creation as `NATIVE_EXECUTION_FAILED`, misreporting
  malformed input as a native failure.

## Change

- New adaptor-local `table.py`: CSV cells must match an ASCII decimal grammar
  (sign, digits, optional fraction and exponent; surrounding space or tab ignored).
  `INVALID_TABLE` locates `rows[i][j]` and reports CSV record number, column label,
  value and recovery. Ragged records are located as `rows[i]`.
- Labels with surrogates or U+FFFE/U+FFFF are rejected at planning (`fromRows`)
  and in CSV headers as `INVALID_TABLE` at `columns[i]`.
- Reverification of retained runs keeps the original shared parser for the
  captured `source.csv`; strictness gates new runs, so legacy receipts still verify.

## Checklist results

| ID | Result |
| --- | --- |
| registration, schema | Unchanged; the JSON schema cannot express the label restriction, which planning enforces as it already does for control characters and duplicates. |
| semantics, tests | `tests/unit/test_calc_allocation.py`: 8 tests that failed before repair (10 failures, 8 errors) and pass after; existing `test_calc_requirements.py` 8 tests pass. |
| execution | Faults occur before the output directory is populated with native work; no native process is launched. |
| guidance, help, discovery | Route recovery text and `docs/calc.md` state the grammar and fault locations. Generated reference and Help are owned by the integration step and were not regenerated here. |
| native-mapping, qualification, maintenance | Not applicable to this change: no native mapping added, `absorbedVersion` untouched. Native qualification is not claimed for it. |

## Native scope

One serial sanity run of a three-row plain-decimal CSV (including spaces and an
exponent) completed and reverified with a retained LibreOffice 26.8.0.3, which is
older than the absorbed 26.8.1 and the 26.8.1 observed on the official download
page. It is not qualification and `absorbedVersion` is unchanged: the change is
host admission only, so the existing native receipt is neither extended nor
renewed.

## Limits

CSV locale conventions (comma decimals, thousands separators) are rejected, not
converted. Content is still read at run time, not during planning, so a bad CSV
is reported when a run starts. Calc remains draft output requiring human review of
unit meaning and tolerances.

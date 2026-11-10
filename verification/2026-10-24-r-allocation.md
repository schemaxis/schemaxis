# R numeric-table and retained-evidence boundary review — 2026-10-24

## Changed scope

`schemaxis.r/1` `linearRegression`, host planning and retained-evidence verification
only. No native mapping, format, publication or numeric behaviour changed; valid
documents plan and verify exactly as before.

- Missing cells (`null`, `NaN`, and text such as `NA`, `N/A` or an empty string) now
  fail as `MISSING_VALUE`; text and boolean cells fail as `UNSUPPORTED_VALUE_TYPE`.
  Both name the cell (`$.training[i][j]`), the predictor or response, and the
  recovery: remove the incomplete row or supply a measurement, or encode the
  variable numerically yourself. Nothing is dropped, imputed or coerced. Infinity,
  out-of-range values and structural errors keep `INVALID_ARGUMENT`.
- Verifying a retained directory whose `authored.json` is pathologically nested no
  longer leaks a raw `RecursionError`, and one that no longer plans is reported as
  `VERIFICATION_FAILED` at `authored.json` with the original planning fault in
  `observed.authoredFault`, rather than as a fresh input fault.

Before repair, the generic `INVALID_ARGUMENT` "expected a finite number" was the only
signal for missing, text and boolean cells, and the nested-JSON case raised an
unstructured exception. Both are reproduced by `tests/unit/test_r_allocation.py`.

## Checklist

| ID | Result |
| --- | --- |
| registration, schema | Unchanged; the authored schema already rejects null, text and boolean cells (example `missing-cell` is schema-invalid). |
| semantics | New classification before native launch; exact fault, location and observed variable tested. |
| native-mapping, execution | Unchanged. Verification fault classification only; evidence digests, launchers and tolerances untouched. |
| discovery | Not applicable; no operation or vocabulary changed. |
| guidance, help | Table-cell explanations and route recovery text name both faults; `docs/r.md` documents the fault table. Generated reference and Help are registered centrally. |
| examples | `r-missing-invalid.json` added as an invalid host example. |
| tests | Nine new host tests; existing R admission and inference tests unchanged and passing. |
| qualification, maintenance | No Rscript was available for this review, so no native run was made and the existing receipt is neither refreshed nor extended. `absorbedVersion` stays 4.6.1; the CRAN R-4 source index listed 4.6.1 as the newest release on this date. |

Draft/human-review limits are unchanged: the route does not choose complete-case
handling, encoding or a model, and the analyst remains responsible for the
consequence of excluding rows.

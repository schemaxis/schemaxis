# Studio string-length validation — 18 October 2026

Operation forms now report declared `minLength` and `maxLength` violations before
inserting a value. For example, an Arrow output name of 41 characters keeps the
form open, reports the 40-character limit and leaves the editor source unchanged.
The server remains authoritative for the complete input contract.

The shared editor validator and conditional-branch matcher count Unicode code
points, with inclusive bounds, following [JSON Schema validation section 6.3](https://json-schema.org/draft/2020-12/json-schema-validation#name-validation-keywords-for-stri).
Placeholder fields use the same helper. Astral characters count once; combining
marks count separately. Unresolved composition markers and intentionally skipped
documents retain their existing treatment. Ambiguous alternatives remain
conservative. Pattern, enum, type and path checks retain their previous behaviour.

## Verification

- Before the core correction, two of three new regression tests failed. The
  focused corrected run passed 22 tests, including the actual Arrow browser flow.
- Independent review passed 37 synthetic probes and found no new diagnostics
  across 216 shipped examples and 36 schemas. Eight of ten mutation probes were
  detected; the remaining cases were an equivalent marker guard and a missing
  singular-wording assertion, which was subsequently added.
- The adjacent placeholder correction discriminates both Unicode counting errors:
  three astral characters satisfy a maximum of three, while two do not satisfy a
  minimum of four. Sixteen focused unit tests and four actual browser checks
  passed. Root reviewed the delegated source delta and final hashes.
- The final serial Studio run covered the exact 52-file list: **404 tests,
  401 passed, 3 existing skips, zero failures**, in 268.2 seconds. It includes
  Arrow, FreeCAD PartDesign, OpenSCAD and QPDF browser authoring checks. Draft
  preservation, cancellation, host validation and atomic undo remain covered.

Changes are confined to the shared editor's `schema-core.mjs`,
`schema-validate.mjs`, `fill-data.mjs`, their regression tests, and the Arrow
browser test. The conservative editor is not a complete JSON Schema validator.
No native application qualification or new adaptor credit is claimed for this
UI change. Earlier native receipts remain evidence of their recorded source
epochs; shared source changes require freshness checks at the next integration.

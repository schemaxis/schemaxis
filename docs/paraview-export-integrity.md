# ParaView export integrity

Scope: explicit ParaView exports (`scenes[].exports`) verified by Schemaxis. This page
describes two checks added to the existing contracts; it does not change the portable
handback or human-revision contracts and it does not qualify scientific accuracy.

## Nonfinite values are refused, not mismatched

A NaN or infinity cannot be compared for equality or within a tolerance. Earlier, a
CSV export of a table containing `nan` wrote the file and then failed with the unhelpful
`VERIFICATION_FAILED: CSV cell differs from input`. Verified exports now fail first with a
structured fault that names the array.

| Fault | Meaning |
| --- | --- |
| `NONFINITE_DATA` | The node being exported holds NaN or an infinity in a compared array or coordinate. `observed` gives `array`, `association`, `tuple`, `component` and the count from the first occurrence. Repair upstream (for example `pvCalculator` `ReplaceInvalidResults`) or export a node without the array. |
| `NONFINITE_ARTIFACT_DATA` | The written file, or its native readback, holds a nonfinite value the input did not. Treat the artifact as corrupt and export again in a new directory. |

Only what each comparison actually compares is checked, so a geometry export (STL, PLY)
is still accepted when point arrays that its loss contract discards hold NaN, but not
when the coordinates do. `table` checks the effective association's arrays and every
numeric cell, `semantic` the points and the arrays present in the input, `pixels` the
scalars and `exact` keeps its existing `NONFINITE_DATA` snapshot check.

## Retained export evidence

`verify` (and the check at the end of `run`) now also re-reads each export artifact's
retained record on the host. It refuses with a stable code when:

- the verification evidence is not an object, names a different comparison than the
  authored one, lacks the fields its comparison writes (rows and columns for `table`,
  record counts for `semantic`, surface cells for `geometry`, a maximum error within
  the authored tolerance for `pixels`), or records a different tolerance
  (`MALFORMED_EXPORT_EVIDENCE`);
- any number in the artifact record is NaN or infinite, which Python's JSON reader
  accepts (`NONFINITE_EVIDENCE`);
- the member list is absent, repeats a file, omits the export file or holds a malformed
  SHA-256 (`MALFORMED_EXPORT_EVIDENCE`);
- the export file is outside its own output directory, has an unmanaged name, or a
  member is outside that directory (`VERIFICATION_FAILED`);
- the export directory holds a file that the record does not list, a listed file is
  missing, a symbolic link is present, or a digest differs (`VERIFICATION_FAILED`).
  The publication layer's `<member>.metadata.json` description beside a listed member is
  the only unlisted name accepted.

These checks establish that the retained directory matches what the native run reported
and that the report is well formed. They do not recompute the scientific comparison. A
receipt edited together with its files can still pass; the receipt is not signed.

## Examples

- `examples/schemaxis/paraview-export-integrity.json`: finite sphere with a calculator
  array exported to CSV and verified as a table.
- `examples/schemaxis/paraview-export-integrity-nonfinite.json`: a three-row table whose
  middle `pressure` is `nan`; expected result `NONFINITE_DATA` (run from the repository
  root because the data file path is relative).

See `verification/2026-10-24-paraview-export-integrity.md` for the exact native scope.

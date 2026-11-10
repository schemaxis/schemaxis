# Apache Arrow typed CSV publication — 25 October 2026

Scope: `schemaxis.apachearrow/1`, `prepareTable`, the new optional `publishCSV`
boolean and the `table.csv` publication it adds, plus an Arrow-to-Arrow artifact
handoff. This note covers only that addition; it does not re-review the rest of
the route.

## Need

Prepared nullable typed rows were published only as Parquet and a JSON report, so a
consumer that wants a declared-schema CSV (or a labelled workbook built from one by
its own adaptor) could not take the selected, renamed table as an artifact.

## Change

`publishCSV` is a boolean, default `false`. Absent and `false` give the same effective
plan, publication list, native configuration, Parquet bytes and report bytes as before.
`true` appends `table.csv` as artifact index 2, a `csvreadback` native stage and a
`csv` object in the report. The file is written by PyArrow 26.0.0 `csv.write_csv` from
the same final post-filter/select/cast/fill table that produces the Parquet file.

The canonical form is closed (UTF-8, no BOM, LF, comma, bare header of the output
names, null as bare `\N`, text and timestamps always quoted with doubled quotes,
bool/int bare, binary64 as shortest round-trip text). The CSV has no type metadata; a
consumer must declare the identical schema. Nothing is inferred, no workbook is
created and formula-looking text is carried as literal data.

Before native work the host encodes the table itself, which budgets the exact encoded
size (quoting, doubled quotes, newlines, fill growth; 8 MiB) and refuses nonnull text
equal to `\N`. Verification then requires `table.csv` to equal the host's canonical
bytes, to parse under the declared output schema to exactly the oracle rows, and to
match a fresh native reopen under that schema.

## Primitive findings (PyArrow and Arrow C++ 26.0.0)

- `csv.WriteOptions` **has** `null_string`, `quoting_header` and `eol` in 26.0.0. Its
  default `null_string` is empty, which this grammar reads as empty text or an invalid
  numeric cell, so the adaptor always sets `\N` explicitly. The cast-to-text and
  `fill_null` workaround was therefore not needed for nulls.
- `quoting_style='needed'` quotes every nonnull string (including `NA` and spaces) and
  leaves numbers and booleans bare; nulls are never quoted. `quoting_header='none'`
  writes bare names.
- A UTC microsecond timestamp is written with a space separator, which is not the
  Schemaxis grammar, so timestamps are first cast natively to text and the first space
  becomes `T`.
- The `float64` layout is Arrow's shortest round-trip text (`1e+10`, `1e-7`, `-0`,
  `5e-324`). The host reproduces it from Python's shortest digits. 400,000 doubles
  (random bit patterns, subnormals, the largest finite value, signed zero, every power
  of ten and neighbours) matched Arrow's cast text, `write_csv` output and the host
  formatter byte for byte; an earlier one-off probe of 1.5 million doubles had also
  matched. This is an observation of 26.0.0, not an upstream guarantee: a different
  layout fails verification instead of being accepted.
- No adaptor-owned CSV writer produces the bytes. The only adaptor-owned formatting is
  the timestamp text conversion done with native compute and the host's independent
  oracle.
- **Discrepancy with the work brief:** a nonnull `\N` cannot currently reach the writer.
  Planning already rejects `\N` as a `fillNull` or filter literal
  (`INVALID_ARROW_LITERAL`), and a `\N` source cell is null. The collision guard
  (`INVALID_ARROW_CSV_NULL_COLLISION`) is therefore an encoder invariant; it is tested
  by injecting a colliding value below the planner, and the end-to-end rejections
  tested are the planner's.

## Checks

| Check | Result |
|---|---|
| `tests/unit/test_apachearrow.py` | 18 tests pass: 12 existing and 6 new native-free tests. Run on Python 3.14 only; no 3.10 or 3.11 interpreter was available, so the new and changed Python files were additionally parsed with the Python 3.10 grammar |
| New host tests | Option closed and absent equals false (plan, config, publications, evidence names); invalid option (`INVALID_ARGUMENT` at `$.publishCSV`) and no writer options; literal canonical bytes; float layout with independent literals and 3,000 seeded exact round trips; quoting, Unicode, newline and formula-looking text; null collision and byte budget refused before a fake interpreter is launched; CSV verification of 21 single-cell/structure edits, truncation and native-snapshot tampering using host-built evidence |
| Focused suites | 138 tests across completion, readiness, kit, architecture, references, Help, capabilities, scaffold, plugins, growth and console references pass |
| Search and Studio | Search acceptance (339) passes; two Arrow browser tests pass, including the new `publishCSV` insert, field Help, host validation and undo; guidance 22 reviewed, 0 pending; generated reference, packaged Help and readiness admission checks pass |
| Native acceptance (`tools/qualify_apachearrow.py`, serial, PyArrow and Arrow C++ 26.0.0, SQLite CLI for the older handoff) | Primary cases (baseline, variant, empty, null-row, new `csv-publication`) with tamper probes and timeout/cancellation; all earlier boundary, subsecond, hostile, SQLite handoff, composition and lifecycle cases; plus the cases below |
| Literal boundary table | 12 rows: int64 and int32 extrema, 2^53+1, signed zero, 5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, rounding boundary, 1e-7, 1e10, null in every column type, empty text, `\Nx` and `x\N` text, Unicode including an emoji, LF/CR/CRLF in text, quotes, commas, padded text, `=SUM(...)`, timestamps at year 0001, 9999, pre-epoch and leap day with 1–6 fractional digits. Hand-written expected bytes, an independent `csv.reader` typed oracle, the native Parquet and CSV reopen snapshots and the report all agree. A second run adds a filter, renames, widening and fills (including `-0`); an empty result publishes only the header and a row null in every nullable column publishes `\N` cells, both with native reopen |
| Compatibility | Absent, explicit `false` and `true` on a retained older numeric/nullable run produce its exact Parquet bytes; absent and `false` also reproduce its report and plan; the retained directory (31 files) was read only and unchanged |
| Standalone verification | Succeeds after the original source is moved away, still checking every CSV cell |
| Hostile controls | 30 CSV and publication controls with ordinary digests, bindings and receipt refreshed (changed values, signed zero, subnormal, maximum finite, layout, null versus empty versus quoted token, quoting, Unicode, newline, formula guard, timestamps, bool spelling, header, CRLF, BOM, final newline, dropped/duplicated rows, native reopen disagreement, forged report digest, removed/dropped/stray publication, falsified option, changed worker) all fail with the pinned semantic cause; the 11 earlier controls also fail on the opted-in run |
| Budget and option before native | An expanding fill is refused with `INVALID_ARROW_CSV_BUDGET` with no native stage artifacts; the same table with the option off is accepted; a non-boolean option creates no run directory |
| Arrow-to-Arrow handoff | `table.csv` (artifact 2) feeds a consumer that declares the schema; native parsing of every typed cell equals the literal rows including `-0`; unchanged reuse; same-path changed bytes invalidate reuse and the new value reaches the consumer; a producer without the option cannot feed artifact 2 (`INVALID_SELECTION`) |
| Lifecycle | In-flight timeout and cancellation on an opted-in run terminate the owned child and leave an unverifiable run with no verification receipt |

## Not run, limits and compatibility

- No Arrow-to-Calc or other downstream consumer was exercised; none is claimed. The
  only consumer exercised is `prepareTable` itself.
- No MPI and no exhaustive Arrow or CSV-dialect coverage. No Python 3.10 execution.
- `implementation()` fingerprints the changed files, so earlier retained Arrow runs fail
  `verify` with the existing "requalify retained output with current code" message and
  must be rerun. Their Parquet and report bytes are reproduced unchanged.
- The registered native qualification receipt is bound to an earlier source digest. The
  runs described here are new acceptance, not that receipt, and nothing was registered.
  The absorbed upstream version (26.0.0) is unchanged.
- Shared generated assets (generated reference schemas and packaged Help) were
  regenerated in the isolated source only.

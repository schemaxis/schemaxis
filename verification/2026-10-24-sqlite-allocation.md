# SQLite boundary review — 24 October 2026

Scope: host and retained-evidence boundaries of `schemaxis.sqlite/1` / `summarise`.
No native mapping, option, format or absorbed version changed; no commit or publication.

## Problems reproduced before repair

1. `verify` on a run directory whose run had failed or been interrupted reported
   `VERIFICATION_FAILED` with a raw missing-file message, because the receipt was read
   before the recorded result. An honest failed run looked like tampering.
2. Run-time source and data faults were located at `$.tables` or at an absolute source path,
   with empty `observed`; missing, symlinked, non-regular and oversize sources, and malformed
   JSON versus wrong shape versus bad cell, differed only in message prose.
3. An orphan foreign key named the declaration but not the offending row.

## Repair

- Failed, incomplete or interrupted runs verify as `INCOMPLETE_EXECUTION`, carrying the
  recorded `status` and `faultCode`. A run recorded as succeeded with a missing or altered
  receipt, or a missing result record, stays `VERIFICATION_FAILED`. Verification of genuine
  succeeded receipts is unchanged: the receipt, launcher, input, schema, row and oracle
  comparisons are untouched.
- Source faults keep `INVALID_TABLE_SOURCE` and data faults `INVALID_TABLE_DATA`, now located at
  `$.tables[i].source` with `observed.table` and `observed.reason` (`missing`, `symlink`,
  `not-regular`, `too-large`, `unreadable`, `malformed-json`, `invalid-shape`,
  `invalid-cell`, `duplicate-key`, `orphan-foreign-key`), plus `row`/`column`/`value` where
  known. Limits, accepted inputs and message recovery text are otherwise unchanged.

## Evidence

`tests/unit/test_sqlite_allocation.py` adds five host tests; four failed before the repair and
all pass after it, one guards that a claimed success without a receipt is still a verification
failure. With `tests/unit/test_sqlite.py` the 13 SQLite host tests pass; the Studio guidance
audit (30 reviewed, 0 pending) and ordinary discovery pass. Two tests drive `run` with a stub
launcher that exits non-zero or prints another version to exercise the retained-failure path;
that is host evidence only, not native qualification.

## Native status and limits

The official download page still lists SQLite **3.54.1** as latest stable, so `absorbedVersion`
is unchanged. No SQLite CLI was available in this review, so no native acceptance was run and the
existing native receipt is neither refreshed nor extended; it may be stale after shared source
changes and is for the maintainers to refresh with `tools/qualify_sqlite.py` against the 3.54.1
CLI. The route remains a bounded draft summary: no arbitrary SQL, existing databases, floats,
Unicode text or other joins.

# Apache Arrow prepareTable completion review — 17 October 2026

Scope: `schemaxis.apachearrow/1`, `prepareTable`. Explicit six-type nullable CSV
to Parquet with source-row filters, projection/rename, int32-to-int64 widening and
explicit null replacement. PyArrow and Arrow C++ 26.0.0 are the bounded native
target on POSIX; host Python 3.10+ remains standard-library-only.

Implementation and documentation passed independent integration review. Shared
reference/Help generation and structural admission passed, and fresh native
qualification is registered for the integrated source. The bounded absorbed
version is 26.0.0.
This note does not claim every Arrow or Parquet feature is supported.

## Twelve-item review

| Item | Owned result and evidence |
|---|---|
| registration | Manifest supplies document route, isolated process runtime, scheduled workflow, composition, explicit native-save and unsupported interactive/MPI decisions. Registry remains data-driven. |
| schema | Every source column/filter/selection field is declared; schema derives from declarations, unknown keys fail, defaults are immutable, cross-field predicates/casts and identifiers are checked before native execution. |
| semantics | Full CSV validation includes filtered-out cells, canonical integers, float bit semantics, quoted null tokens, UTC-only microseconds and explicit replacement. Output expansion is bounded before native launch. |
| native-mapping | Official CSV/compute/Table/Parquet APIs are mapped explicitly. Source and reopened native snapshots are compared cell-by-cell to the independent host reference. |
| execution | Owned isolated workers, total timeout, POSIX resource caps, process-group cancellation, immutable captures, current implementation fingerprints, exact command/input/publication binding and independent Parquet decoder. |
| discovery | Reviewed app-owned positive, synonymous, ambiguous and negative cases; capability matching checked. Actual Studio intent discovery and packaged operation Help passed. |
| guidance | All 21 operation/field records reviewed, including nested array items. Typed null, spelling, order, omission, UTC, precision and unsupported metadata/unit conventions are explained. |
| help | Local guide includes exact contracts, CLI use, examples, reports, handoff, faults and primary API/spec links. Generated reference/packaged Help is an integration responsibility. |
| examples | Baseline, selection/widening, empty, null-row, invalid-cast, two Studio starters with required source picker, and actual SQLite CSV handoff recipe. Literal expectations are authored independently. |
| tests | Ten focused host tests cover immutable plans, exact oracle, malformed source/Parquet, resource refusals, import boundaries and Studio insertion/edit/undo. Native acceptance adds all semantic/lifecycle/workflow cases described below. |
| qualification | `tools/qualify_apachearrow.py` produces a source-bound receipt for baseline/variant/empty/null-row plus additional native/hostile checks. Full acceptance passed again after shared generation, and current common qualification is registered. |
| maintenance | Official stable source records 26.0.0 released 9 October 2026. Pinned worker rejects incompatible native versions. Reviewed bounded native acceptance establishes the absorbed version. |

## Verification performed

The first complete native acceptance run passed baseline, selected/widened variant,
empty result and all-null-row cases. Additional real native cases established:

- int64 extrema and >2^53, int32 extrema, exact binary64 bits for negative zero,
  smallest subnormal, maximum finite double and a long decimal rounding boundary;
- four-digit-year UTC endpoints, pre-epoch and leap-day microseconds, quoted null,
  empty/escaped-quote/embedded-newline text and independent native CSV agreement;
- explicit null fill for float, bool, text and timestamps;
- 2,400 rows across three row groups, multiple pages and exact all-null timestamp
  and mixed-null text/boolean columns;
- standalone verification after moving the original source away, with current-source
  reuse correctly refusing the unavailable source;
- actual SQLite CSV artifact handoff preserving null versus empty text, native
  unchanged reuse and same-path changed-source invalidation with a changed sum;
- finite two-state composition and owned-child timeout/cancellation with confirmed
  process termination.

Eleven saved-evidence adversaries passed rejection, including changed native source
snapshot, float zero sign, fresh readback, report, worker, Parquet payload, capture,
authored selection and publication/evidence membership. Hashes and relevant
consumed-input bindings were refreshed in the payload/capture tests; the independent
value oracle still rejected them.

Host tests separately reserialize valid Compact-Thrift footers after changing
schema, UTC flag, nullability, wire types, external chunks, sizes, offsets,
compression/dictionary and page counts. They also reject duplicate/overflow/
noncanonical varints, bad framing, definition-level and boolean padding. The binary
host fixture is native Parquet written by 26.0.0 from the repository's authored
measurement CSV; literal expected values are retained in the tests.

Normal verification performs bounded regular-file reads **before** parsing. It
checks all metadata wire types/allowed fields, exact physical/logical leaf schema,
all values and masks, page/chunk/row-group counts and exact contiguous file regions.
Arrow-generated reports or same-engine readback cannot substitute for these checks.

## Qualification limits and intentional refusals

The 246-line independent decoder is a closed output checker, not a general Parquet
importer. Compression, dictionaries, INT96, nested/extension/decimal/binary types,
external chunks, arbitrary metadata, encryption and alternate page encodings fail.
`store_schema=False` avoids an opaque second schema interpretation; authored field
metadata and units are rejected, not silently dropped. No unit conversion, SQL,
join/aggregate operation, timezone inference, native GUI, live state or MPI claim.

The native wheel is an external free runtime, not a new host dependency. No
licence files, machine configuration or existing user data were changed. Shared
schema storage and publication metadata continue through the standard framework.

Reproduce with `PYTHONPATH=src python3 -m unittest tests.unit.test_apachearrow -q`,
`PYTHONPATH=src python3 tools/studio_guidance.py --app apachearrow --check`, and
`PYTHONPATH=src python3 tools/qualify_apachearrow.py --apachearrow /absolute/venv/bin/python --sqlite /absolute/sqlite3 --output-directory fresh-evidence`.
Register only the receipt matching the final integrated source.

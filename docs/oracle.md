# Oracle Database adaptor

The Oracle adaptor lets a document describe **what** to do with Oracle tables — inspect a
schema, load captured rows, publish a relational report, or run an atomic transaction —
without authoring SQL, PL/SQL or cursor code. The host plans and generates the SQL, a
separate worker process runs it with [python-oracledb](https://python-oracledb.readthedocs.io/en/latest/)
in Thin mode, and the host verifies every native result against an independent reference.

The supported scope combines relational and bounded document workflows. Its status, the implemented families and
the families that are not yet implemented are listed in the
[capability-family map](design/oracle-coverage.md). A discovery status is native-qualified only when a
source-current registered receipt exists (`schemaxis readiness --app oracle`).

## Setup

* Use a **dedicated Python interpreter** that has python-oracledb installed and pass it with
  `--oracle` (or configure it with `schemaxis configure`). The host Python never imports the
  driver; discovery, schemas and planning work without it.
* Put the credentials in the host environment, by variable *name* only:

  | Variable (default for profile `free_local`) | Meaning |
  | --- | --- |
  | `SCHEMAXIS_ORACLE_FREE_LOCAL_USER` | database user |
  | `SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD` | password |
  | `SCHEMAXIS_ORACLE_FREE_LOCAL_DSN` | connect string, for example `host:port/service` |

  A document names only `connection.profile` (and, optionally, other variable names that
  start with `SCHEMAXIS_ORACLE_`). Credential values are never written to documents, plans,
  logs or receipts. Error messages redact whole credential values (and the host, port and
  service of the connect string) but never rewrite structured row data. The password and connect
  string must be at least eight characters: shorter values cannot be proven absent from evidence,
  so the run is refused before any database work. Credentials that collide with fixed
  fault/outcome vocabulary (for example `ORACLE_CREDENTIAL_LEAK` or
  `databaseWorkCompleted`, and required outcome/status values such as `committed`
  or `succeeded`) are also refused before run files or native work; choose
  unrelated values. The structured refusal uses public protocol names and never
  interpolates the credential. A value literally equal to a required JSON key can
  coincide with that public key in any structured refusal; such values are unsupported
  configurations, not secret-scan exceptions. After the final status write, every retained
  file is scanned for the password and connect string in UTF-8/UTF-16, JSON-escaped,
  percent-encoded and base64 forms, and a file that contains one is blanked and the run fails. A
  table value that equals the password is therefore also refused. The user name is session identity
  and is recorded in evidence by design.
* The adaptor works in the connected schema, uses a Thin connection and refuses a Thick one.
  The database character set must be AL32UTF8. `boolean` columns need Oracle Database 23 or later.
* Use a disposable schema for experiments: `load` and `mutate` create tables.

## Operations

| Operation | Purpose | Main fields |
| --- | --- | --- |
| `inspect` | Snapshot tables, columns, keys, indexes, views and sequences; compare with declared tables | `inspection`, optional `tables` |
| `load` | Create tables and import captured JSON/CSV rows; verify from a fresh connection | `tables`, `setup` |
| `report` | Joins, filters, groups, windows, set operations; exact ordered result | `tables`, `report` |
| `mutate` | Insert/update/delete/merge steps, savepoints, commit or rollback | `tables`, `transaction` |

All operations share the same records: a **table** (typed columns, primary key, unique,
foreign and check constraints, optional `source`), an **operand** (column, literal, derived
value or measure), a **condition** (named terms with SQL three-valued logic), a
**derived value**, a **measure** and a **step**. A condition or derived value is defined once
by name and referred to later, so deeper logic is built by naming, not by nesting.

```json
{"version": "schemaxis.oracle/1", "operation": "report",
 "connection": {"profile": "free_local"},
 "tables": ["... declared tables with sources ..."],
 "report": {"selects": [{"from": {"table": "customers", "alias": "c"},
   "joins": [{"type": "left", "table": "orders", "alias": "o", "on": [{"left": "c.id", "right": "o.customer_id"}]}],
   "groupBy": [{"column": "c.region"}],
   "measures": [{"name": "revenue", "function": "sum", "argument": {"column": "o.total"}}],
   "columns": [{"name": "region", "operand": {"column": "c.region"}},
               {"name": "revenue", "operand": {"measure": "revenue"}}]}],
   "orderBy": [{"column": "region"}]}}
```

See the runnable [revenue report](../examples/schemaxis/oracle-report-revenue.json), its
[full-join variant](../examples/schemaxis/oracle-report-variant.json), the
[three-table report](../examples/schemaxis/oracle-report-lines.json) with a derived value,
HAVING and a rank window, the [load](../examples/schemaxis/oracle-load.json) and
[inspect](../examples/schemaxis/oracle-inspect.json) documents, three
[transaction](../examples/schemaxis/oracle-mutate-transfer.json)
[examples](../examples/schemaxis/oracle-mutate-savepoint.json)
([rollback](../examples/schemaxis/oracle-mutate-rollback.json)), and a workflow that loads
tables, reuses their declarations with document references, reports on them and hands the
typed CSV to [Calc](../examples/schemaxis/oracle-calc-typed-workflow.json).

## Types and policies

| Type | Exact representation | Policy |
| --- | --- | --- |
| `number` | integer or decimal text, up to 38 digits | Floats are refused. Extra fractional digits are refused unless `scalePolicy` is `round` (half away from zero). Oracle does not remember trailing zeros, so published numbers are canonical decimal text (`80`, not `80.00`). |
| `varchar2` | Unicode text, `length` characters (1–1000) | Binary (code point) ordering and comparison. **Empty text is NULL in Oracle:** it is refused unless `emptyText` is `null`. NUL characters, lone surrogates and the text `\N` are refused. |
| `date` | `YYYY-MM-DDTHH:MM:SS` | Whole seconds, no zone. Date-only text means midnight. |
| `timestamp` | adds up to six fractional digits | Wall clock, no zone; more digits than declared are refused, not rounded. |
| `timestampTz` | adds `Z` or `±HH:MM` | Fixed numeric offsets only (−14:00…+14:00); no region names or daylight-saving rules. The stored offset is preserved and compared by instant. Not usable as a group key, distinct value or set-operation value because equal instants with different offsets leave the representative unspecified. |
| `raw` | non-empty hexadecimal text | `length` bytes (1–2000). Empty RAW is NULL in Oracle and is refused. |
| `clob` | non-empty Unicode document | Up to 262144 UTF-16 code units (Oracle LOB length); NULL is distinct. Empty LOBs, NCLOB and BFILE are not supported. |
| `blob` | non-empty hexadecimal text | Up to 262144 bytes; exact bytes round-trip through load/report/mutate. |
| `json` | standard JSON text | Canonical key order and exact decimal numbers (38 stored digits); duplicate keys, nonfinite numbers and excessive nesting are refused. Up to 262144 UTF-8 bytes, 32 levels and 10000 values. SQL NULL differs from the JSON text `null`. |
| `boolean` | `true` / `false` | Oracle Database 23 or later. |

Conditions use three-valued logic: a comparison with NULL is *unknown*, and rows or check
constraints behave as Oracle's do (a row is kept only when a condition is TRUE; a check fails
only when it is FALSE). Comparing with a NULL literal is refused; use the `isNull` operator.
Types are never converted implicitly. `upper`/`lower` are verified for ASCII text only;
`trim`, `substring` and `concat` return NULL where Oracle's would be empty text.

CSV output writes NULL as `\N` and exact decimal text for numbers. JSON output uses `null`,
exact decimal strings (or, with `report.numbers: "jsonNumber"`, JSON numbers that a double
represents exactly; anything else is refused).

## Document values and JSON scalars

[Document report](../examples/schemaxis/oracle-report-documents.json) and
[document load](../examples/schemaxis/oracle-load-documents.json) reuse the same table
records as relational reports. CLOB and BLOB values are bound with the driver's LOB
types and read through bounded LOB handles. JSON uses Oracle's native JSON column and
constructor; output uses JSON_SERIALIZE, then exact independent canonicalisation.
Rows and publications remain captured, digest-bound JSON/CSV artifacts.

Use named derived functions `jsonNumber`, `jsonText` and `jsonBoolean` with one JSON
operand and a `path`, for example `$.samples[0].value`. Paths allow only named
members and zero-based indexes. Missing members and JSON null yield SQL NULL;
empty extracted text follows Oracle's VARCHAR2 NULL policy. Boolean extraction also accepts the strings true/false without case sensitivity.
Closed paths follow Oracle lax semantics: member steps unwrap one array level,
index steps wrap a scalar as a singleton array, missing steps yield NULL, and
multiple scalar matches refuse. Numeric text can be
explicitly extracted as a number; jsonText converts numeric/boolean scalars to
text. Objects/arrays in a scalar position and incompatible types are refused.
Extracted text is limited to 1000 UTF-8 bytes. The reference checks every result.

LOB/JSON columns are projected directly, assigned as typed values, or tested with
`isNull`. They cannot be keys, joins, grouping/window partition keys, aggregate
arguments, ordered values, set combinations or DISTINCT values. Extract ordinary
JSON scalars first to filter, join through a materialised scalar table, group,
order and aggregate. There is no arbitrary JSON path, SQL fragment or script.

## Verification

Every run keeps three worker stages with separate sessions:

1. **identify** — connects, records the driver, server and session identity, character set and the
   dictionary state of the declared objects. Name-conflict and drift decisions are made from this
   before any change; a taken table name is refused, never replaced.
2. **apply** — creates and loads the tables, runs the report or transaction on one session, and,
   for transactions, reads the tables through a second *observer* connection before and after
   the finish.
3. **readback** — a fresh process and connection reads the dictionary and every table again,
   then drops scratch tables when `setup.retain` is false.

The host recomputes the expected rows with a Decimal/datetime/three-valued-logic reference and
compares them with what Oracle returned: loaded rows, report rows, in-transaction state,
observer state (uncommitted work must be invisible), final state and per-step row counts. The
generated statements, programs, worker source and every retained file are hash-bound; `verify`
recomputes all of it and rejects altered, stale or missing evidence.

* A report whose order is ambiguous (ties across `limit`/`offset`, or under `rowNumber` and
  running windows) is refused rather than published in arbitrary order.
* Stored NUMBER values hold at most 38 significant digits and are compared exactly. Oracle computes
  with up to 40 digits (1/3 is `.333…` with forty 3s), so computed results (division, average, sums,
  derived arithmetic) are decoded under a separate 40-digit result policy and compared at 36
  significant digits. Assigning a computed value to a column rounds it to 38 digits and then to
  the column scale; the host refuses a scale or fractional-second loss unless the column's
  `scalePolicy` is `round`, and predicts precision (ORA-01438) and length (ORA-12899) overflow,
  before anything commits. For existing tables this prospective reference runs inside the same
worker snapshot before the first DML; the uncommitted native rows must also match
the reference before the final COMMIT. The isolated worker bundles only trusted
repository Python and needs no installed Schemaxis package.
* Dates are read with a signed year mask: a BC (negative-year) value is refused.
* Reports read external rows and the result inside one query-only SERIALIZABLE transaction: Oracle
  gives it a transaction-level snapshot, so both reads see the same committed state even while another
  session writes. The adaptor itself guarantees that nothing after the seed commit writes (Oracle's
  `READ ONLY` mode is not used; observed natively, it fails with ORA-01466 straight after DDL). The native row
  order must already follow the declared `orderBy` before ties are settled.
* A transaction with `enforcement: "predict"` (the default) is refused before the database is
  touched when the reference predicts a constraint violation; `enforcement: "database"` sends
  it to Oracle, requires Oracle's own refusal, and verifies that the rollback left the tables
  unchanged.

## DDL and transaction boundaries

New tables request `SEGMENT CREATION IMMEDIATE` so an empty table is usable by
a subsequent SERIALIZABLE mutation. Oracle refuses serializable writes to fresh
external deferred-segment tables with ORA-08177; this is reported as
`ORACLE_SERIALIZATION_CONFLICT`, rolled back and never silently replayed. Provision
external ledgers with immediate segment creation before use. Concurrent writers
can produce the same refusal; inspect the current state and ledger before a fresh
explicit attempt. See the [Oracle segment policy](https://docs.oracle.com/en/database/oracle/oracle-database/18/vldbg/partition-create-tables-indexes.html).

`CREATE TABLE`, `COMMENT` and `DROP TABLE` commit implicitly in Oracle and cannot be rolled
back. A run commits the seed rows once, then starts the transaction under test, so the
verified transaction never contains DDL. There is no replace mode: a run never drops a table
it did not create. Cleanup (`setup.retain: false`) drops only tables whose creation the worker
recorded as complete in this run and that still carry this adaptor's marker comment; a `CREATE`
that failed in flight is reported (`possiblyCreated`), not dropped. If a `COMMIT` fails in a way
that leaves its outcome unknown, the run reports `ORACLE_COMMIT_OUTCOME_UNKNOWN`, records what a
fresh session observed, keeps every table as evidence, and never replays the transaction. Terminating a worker abandons its
session, and Oracle rolls back uncommitted work.

## Faults and recovery

| Code | Meaning and recovery |
| --- | --- |
| `INVALID_ORACLE_NAME/TABLE/QUERY/TRANSACTION/VALUE/SOURCE/CONNECTION` | A document or captured value is invalid; read the location and `observed.reason`. Nothing was sent to Oracle. |
| `ORACLE_CREDENTIALS_MISSING` | A named environment variable is not set. |
| `ORACLE_AUTHENTICATION_FAILED`, `ORACLE_UNAVAILABLE`, `ORACLE_CALL_TIMEOUT` | Check the profile values, listener and timeouts; the failed values are not echoed. |
| `ORACLE_DRIVER_UNAVAILABLE`, `UNSUPPORTED_NATIVE_VERSION`, `ORACLE_UNSUPPORTED_CHARSET` | Install python-oracledb 2 or later in the `--oracle` interpreter, or use an AL32UTF8 and (for boolean) Oracle 23 or later database. |
| `ORACLE_OBJECT_EXISTS`, `ORACLE_OBJECT_MISSING`, `ORACLE_DRIFT` | Name conflicts and declaration drift, found before changes. |
| `ORACLE_CREDENTIAL_UNSCANNABLE`, `ORACLE_CREDENTIAL_LEAK` | A credential too short to scan for is refused before any database work; a leaked value blanks the file and fails the run. |
| `ORACLE_CONSTRAINT_VIOLATION`, `ORACLE_ROWCOUNT_MISMATCH`, `ORACLE_ARITHMETIC_ERROR` | The transaction was rolled back; `observed.rollbackVerified` reports the independent check. |
| `ORACLE_COMMIT_OUTCOME_UNKNOWN` | Do not rerun; inspect the tables first. |
| `ORACLE_AMBIGUOUS_ORDER`, `ORACLE_UNVERIFIABLE_VALUE`, `ORACLE_LOSSY_NUMBER`, `ORACLE_AMBIGUOUS_CSV` | The result cannot be published faithfully; add order keys or change the report. |
| `VERIFICATION_FAILED`, `INCOMPLETE_EXECUTION` | Evidence is altered, stale, or from a run that did not finish. |

## Table names and isolation between runs

Scratch tables (`setup.retain: false`, the default for `report` and `mutate`) are created under run-unique
physical names, `<name>_<5 hex characters of the run id>` (a declared name may be at most 24 characters so
that the result fits Oracle's traditional 30). Two jobs that stage the same logical table therefore never
collide, a same-named table that already exists is left alone, and cleanup can only reach this run's own
tables. Results, programs and evidence stay keyed by the declared (logical) names, and the verifier maps the
dictionary back to them. Retained tables (`setup.retain: true`) keep their declared names so that people can
find them; a taken name is refused. External tables are never renamed.

## Publications and reuse

`report` publishes `report.json` (columns and rows; artifact index 0) and `report.csv` (typed CSV with
`\N` for NULL; index 1). `load` publishes `load-summary.json` and one `table-<name>.csv` per created
table; `inspect` publishes `snapshot.json`; `mutate` publishes `transaction.json` and
`state-after.json`. The framework's own `result.json` status file is separate.

A live database's rows and schema are not part of any input digest, so Oracle runs are never reused
by input identity; every execution, including a workflow resume, runs again. A transaction on tables the run
creates starts from captured sources, so a retry never re-applies effects to them. A transaction on
existing tables is protected by an idempotency ledger instead (next section).

## Changing existing tables

Declare the table `external: true` and use ordinary steps. Because the host does not hold such a table's rows,
the transaction must:

* run `isolation: "serializable"`, so the adaptor's **base read** of each existing table and every change see
  one snapshot (a concurrent writer to the same rows is refused by Oracle, not silently merged);
* use `enforcement: "database"`: the host cannot predict constraint or precision refusals for unseen rows, so
  Oracle must refuse them, and a refusal rolls everything back;
* declare `idempotency`: an existing ledger table (declared external; a NOT NULL varchar2 primary-key column and a
  NOT NULL varchar2(64) digest column, no other NOT NULL columns) and a key. The adaptor adds, in the SAME
  transaction, a check that the key is not recorded with a different change (`ORACLE_IDEMPOTENCY_CONFLICT`), a
  check that it is not recorded at all (`ORACLE_ALREADY_APPLIED`, nothing changed), and an insert recording the
  key with a SHA-256 digest of the change. A retry after an ambiguous outcome therefore cannot apply the change
  twice; an unknown commit outcome is still reported as such and the ledger is the way to learn what happened.

Mutation tables must declare their complete column and constraint shape. Before
any base-row read or DML, the worker checks dictionary metadata and refuses enabled
triggers (including autonomous triggers), virtual/default columns, function/domain
indexes, enabled row policies, REFERENCES grants to other users, and incoming
CASCADE/SET NULL references from undeclared children. These mechanisms can execute
code or change rows outside the verified declaration. Declare same-schema children
and their constraints to model cascading effects; ordinary triggers remain compatible
with read-only reports. The contract assumes other privileged sessions do not change
schema mechanisms during the run; it does not control administrative users.
`ORACLE_UNDECLARED_EFFECTS` identifies the refused mechanisms and confirms that no
mutation DML started. Schema setup and administration stay outside this operation.

The reference then starts from the base read, simulates the steps, and the verifier compares the in-transaction
view, an observer session before and after the finish, and a fresh readback with that simulation. It creates, drops
and alters nothing: external tables are never touched by DDL. A concurrent writer between the base read and the
observer reads shows up as a verification difference that names it as the usual cause.

## Limits and what is not here

Up to 8 tables, 32 columns, 5000 rows per table, 4 MiB per source and 10000 result rows.
No authored SQL, PL/SQL, packages, streaming/empty LOBs, NCLOB/BFILE, arbitrary SQL/JSON paths, vectors, object/XML types, AQ, notifications,
schema evolution beyond creating (and, on request, dropping) the run's own tables, administration or Thick-only
features. See the [coverage map](design/oracle-coverage.md) for the complete family list.

Native APIs: [driver LOB handling](https://python-oracledb.readthedocs.io/en/latest/user_guide/lob_data.html), [JSON_VALUE](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/JSON_VALUE.html), [JSON_SERIALIZE](https://docs.oracle.com/en/database/oracle/oracle-database/19/adjsn/oracle-sql-function-json_serialize.html).

Post-native failures preserve the database outcome even when publication, verification,
credential scanning, cancellation, deadlines or final status writing fail. A completed
COMMIT is not undone by a later observer failure or rollback of an empty session.
Readback and cleanup status are reported separately; an unverified cleanup is not
reported as a successful drop. Do not replay committed or unknown work automatically.
Credential refusals identify leaking files by ordinal number rather than filename;
leaking contents are emptied, returned dynamic fault values are redacted, and the
replacement failure status is scanned again with a bounded retry. If no safe status
can be written, it remains empty rather than retaining a false success.

If a load/report seed COMMIT was acknowledged before a later worker failure, the
fault retains that durable seed outcome. An incomplete report is labelled
`seed rows committed; report incomplete`, with `seedCommitCompleted: true` and
`databaseWorkCompleted: false`; it does not claim the failed report query completed.
A rollback of the later read-only transaction cannot undo those committed seed rows.

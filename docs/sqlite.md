# SQLite relational summaries

Use `schemaxis.sqlite/1` with `operation: summarise` to turn captured typed JSON
tables into a fresh relational database and an exact grouped report. Declare
primary/foreign keys, optionally join a base table to one parent, filter an integer
column by an inclusive minimum, and group rows to count and sum integer amounts.
The qualified native application is the SQLite **3.54.1 CLI**, released 16 October
2026 on Linux x64 (POSIX process/resource isolation). Python 3.10+ on the host needs only the standard library; discovery and planning
do not import a native application or execute SQL.

## Start with a report

Open [regional sales](../examples/schemaxis/sqlite-sales.json), replace both
`tables[*].source` placeholders with absolute paths to
[departments](../examples/schemaxis/fixtures/sqlite/departments.json) and
[sales](../examples/schemaxis/fixtures/sqlite/sales.json), and configure the absolute
`sqlite3` executable with `schemaxis configure` or pass `--sqlite` when running.

```sh
schemaxis plan sales.json
schemaxis run sales.json --sqlite /absolute/path/sqlite3 --output-directory fresh-report
schemaxis verify fresh-report
```

The source format is a JSON array of row objects. Every row contains exactly the
declared column names. Example: `[{"id": 1, "region": "North"}]`. Duplicate JSON
object keys, floats and booleans in INTEGER columns are errors. The source is a
regular local `.json` file (at most 1 MiB); file symlinks and network resources are
excluded. Captured source bytes are immutable evidence and remain sufficient for
verification after the original source changes or disappears.

The example imports departments before sales, links `sales.department` to
`departments.id`, groups by `departments.region` and sums `sales.amount`. Its
literal output rows are `[null,1,null]`, `["",1,0]`, `["North",3,300]`, and
`["South",1,-30]`. The sales row with null department is omitted by the inner join.
The [changed threshold](../examples/schemaxis/sqlite-sales-variant.json) keeps IDs
at least 3, reducing North to one row totalling 200. The
[empty report](../examples/schemaxis/sqlite-empty.json) publishes headers and zero
rows. The [single-table report](../examples/schemaxis/sqlite-single-table.json)
groups the nullable integer department key without a join. A
[non-key join](../examples/schemaxis/sqlite-key-invalid.json) fails before execution.
Studio includes editable sales and single-table starters and nested field Help.

## Types, keys and relational meaning

Declare 1–4 tables, each with 1–12 columns and 0–2048 rows. Identifiers use distinct
lower-case ASCII letters, digits and underscores, beginning with a letter, at
most 40 characters. SQLite internal identifiers are excluded. INTEGER means an
actual JSON integer in ±1000000000; TEXT means at most 256 printable ASCII
characters, excluding the reserved CSV null token `\N`. There is no float, decimal,
date, binary, locale or unit conversion. SQL literals and identifiers are generated
and quoted from these validated declarations; authored SQL and expressions are
never accepted.

`nullable` defaults to false. Actual JSON null is the only missing value. Empty
strings, zero and text case remain distinct. Each table names one nonnullable
unique primary key. Foreign keys refer to an earlier table's primary key and must
have the same type. Every nonnull foreign key must match a parent even when its
row would later be filtered out. A nullable foreign key may be null.

`from` selects the base table. Optional `join` must exactly follow one declared
base foreign key to a parent primary key. This is an inner join: null local keys
produce no joined row; unique parent keys prevent multiplication. Omit `join` for
single-table reporting. Optional `where` keeps values greater than or equal to
`minimum`; null values fail the filter. Count and sum occur **after** join/filter.

`groupBy` lists 1–3 distinct qualified `table.column` names. Binary case-sensitive
ascending order places null before other values; numeric keys sort numerically.
Output names `g0`, `g1`, `g2` follow that list, then `row_count` and `total`.
`sum` must select INTEGER: null amounts are ignored, an all-null group total is
null, and count includes all surviving rows. Empty results have zero groups.
Integer totals remain exact; the oracle rejects any total outside ±2^53 (the row
and cell caps currently impose a smaller bound).

## Outputs and workflow handoffs

Publications have stable order: **0** `summary.sqlite` (fresh STRICT database),
**1** `summary.json` (`columns` and typed `rows`), **2** `summary.csv`, **3**
`schema.sql`. CSV encodes null as `\N`, with empty strings preserved as empty cells;
JSON and the database preserve integer/text/null types. No precision or units are
inferred. The database contains all imported rows, including rows dropped by the
report filter or inner join. It is suitable for independent read-only inspection.

Normal workflow execution, shared references, closed expressions and finite
studies are supported. A downstream numeric field can use a verified JSON result,
for example `{"$value":"report","artifact":1,"path":"/rows/2/2"}`; row positions
are meaningful only for the declared deterministic grouping/order. Match units
and nullability explicitly. The adaptor does not accept an arbitrary existing
database or infer that another adaptor's table format is compatible. Source byte
hashes participate in workflow reuse: unchanged inputs reuse, changed bytes at
the same path create a new verified attempt. Schema evidence uses the framework's
shared schema store automatically.

## Verification and recovery

Execution uses isolated owned CLI processes for version, import and read-only
query. Trusted generated SQL, command launchers, native input hashes, submissions,
stdout/stderr, captures and exact publication membership are retained. Startup
configuration is disabled with `-init /dev/null`, a minimal environment and safe
mode; extensions and auxiliary file functions are excluded. Fresh directories
prevent existing database mutation. Limits include a total timeout, native CPU
30 s, 512 MiB address space, 16 MiB file cap, and bounded input/output reads.
Cancellation terminates the owned process group and leaves failed evidence.

Verification independently reopens the database with Python's standard library
in read-only immutable mode; compares the exact table schema, every typed row,
object membership, integrity and foreign keys; and compares raw CLI query JSON
against a literal nested-loop Python join/filter/group oracle. JSON/CSV outputs
must match that oracle exactly. Successful CLI exit or a database file alone is
insufficient. This is bounded verification, not qualification of all SQL features.

`INVALID_TABLE_IDENTIFIER` asks for unique permitted identifiers;
`INVALID_TABLE_KEY` asks for a nonnullable unique primary key and an earlier same-type
parent; `INVALID_TABLE_QUERY` asks for qualified active columns and the exact declared
FK join; `INVALID_TABLE_SOURCE` asks for a bounded local regular JSON file;
`INVALID_TABLE_DATA` identifies type, null, column or key problems. Correct inputs
and retry in a fresh output directory. `INTERPRETER_NOT_FOUND` requires an absolute
CLI executable; `UNSUPPORTED_NATIVE_VERSION` requires requalification before using
another version. `VERIFICATION_FAILED` means retain the evidence and investigate;
do not relabel the run as verified.

No arbitrary SQL, scripts, extension loading, triggers, views, left/many-to-many
joins, existing database editing, network, decimals, Unicode text, live inspection,
MPI or interactive reverse editing is supported.

## Public API and maintenance

The native mapping uses official [CLI startup/safe mode](https://www.sqlite.org/cli.html),
[STRICT tables](https://www.sqlite.org/stricttables.html),
[SELECT](https://www.sqlite.org/lang_select.html),
[COUNT/SUM](https://www.sqlite.org/lang_aggfunc.html),
[foreign keys](https://www.sqlite.org/foreignkeys.html) and
[PRAGMA checks](https://www.sqlite.org/pragma.html).
Latest stable was checked on the official [download page](https://www.sqlite.org/download.html)
and [3.54.1 release log](https://www.sqlite.org/releaselog/3_54_1.html).
Run `tools/qualify_sqlite.py` for native baseline/variant/empty/single-table,
hostile tamper, lifecycle and workflow checks. Source-bound qualification must be
refreshed after shared implementation or generated-reference changes. See the
[completion review](../verification/2026-10-17-sqlite-completion.md) and the generated
[operation reference](generated/sqlite-operations.md).

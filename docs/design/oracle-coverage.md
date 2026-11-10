# Oracle Database adaptor: capability-family map

This map keeps two denominators visible and separate:

1. the **whole application** — every public Oracle Database capability family relevant to a
   general-purpose application adaptor, including the ones that are excluded or not yet
   started; and
2. the **implemented workflow surface** — the intent-oriented operations the adaptor offers
   today and the verification behind them.

It is a planning and status inventory, not registration metadata. Breadth, abstraction quality
and evidence confidence are reported separately. A family is **complete** only when it is
implemented *and* natively qualified, or has a reviewed exclusion. Missing time, a difficult API,
"out of scope" alone, or an unavailable local runtime is not an exclusion reason. A runtime,
licence or access obstacle remains a visible blocker and never counts as native acceptance.

Status words: **native-qualified (partial)** means source-current bounded native
acceptance exists for the described implemented surface, not that the whole family
is complete. **Unimplemented** and **proposed exclusion** remain explicit gaps.
Runtime/licence/access obstacles never count as qualification.

## Current supported scope

Date: 3 November 2026. The complete public qualifier passed with nine shared native
readiness cases and additional relational/document/transaction controls. The observed
runtime is python-oracledb 26.1.0 Thin / Oracle AI Database 26ai Free 23.26.3.0.0,
AL32UTF8. Registration follows final shared generation at integration; it is distinct
from these newly run bounded observations. See the
[current verification note](../../verification/2026-11-03-oracle-completion.md).

| ID | Family | Status | What exists | Not yet / limits |
| --- | --- | --- | --- | --- |
| C01 | Connection and session identity | native-qualified (partial) | Host-held profile by environment variable *name*; bounded connect/call timeouts; Thin-only; driver, server, schema and character-set identity recorded; credential redaction and run-directory credential scan | Pooling, DRCP, proxy users, edition-based redefinition, session tagging, wallets/TLS options |
| C02 | Schema and data dictionary inspection | native-qualified (partial) | Tables, columns, types, keys, unique constraints, check-constraint count, indexes, views, sequences; digest-stable snapshot; two-connection stability; drift against declared tables | Check-constraint text, privileges, synonyms, triggers, partitions, comments beyond the managed marker, snapshot diff between runs |
| C03 | Scalar relational types | native-qualified (partial) | NUMBER (exact, scale policy), VARCHAR2 CHAR semantics with Unicode and empty-string-is-NULL policy, DATE, TIMESTAMP(0–6), TIMESTAMP WITH TIME ZONE (fixed offset), RAW, BOOLEAN | FLOAT/BINARY_DOUBLE/BINARY_FLOAT, CHAR/NVARCHAR2/NCHAR, TIMESTAMP WITH LOCAL TIME ZONE, intervals, ROWID, 7–9 fractional digits, region time zones |
| C04 | Table and constraint definitions | native-qualified (partial) | CREATE TABLE with NOT NULL, primary, unique, foreign (NO ACTION, CASCADE, SET NULL) and check constraints; dependency order; dictionary readback; DDL auto-commit boundary documented and recorded | Column defaults, identity/virtual columns, deferrable constraints, composite-type columns, partitioning, ALTER |
| C05 | Data loading and extraction | native-qualified (partial) | Captured typed JSON/CSV, bounded array binds, one committed batch, fresh-connection readback and row accounting, typed JSON/CSV publication of results and loaded tables | Batch-error collection, direct-path load, streaming fetch of large tables, extraction of arbitrary existing tables without a report |
| C06 | Relational selection | native-qualified (partial) | Projection, typed null-aware conditions, binary ordering with explicit NULL placement, limit/offset with tie refusal, empty and boundary cases | Explicit snapshot consistency (flashback/SCN), subqueries |
| C07 | Joins and set operations | native-qualified (partial) | Multi-table inner/left/right/full equi-joins, self-joins by alias, union/union all/intersect/except, distinct | Cross/non-equi/lateral joins, anti/semi-join shorthand |
| C08 | Aggregation and analytics | native-qualified (partial) | count/countAll/countDistinct/sum/average/minimum/maximum, group by, having, rank/denseRank/rowNumber/runningSum/runningCount, date-part grouping via derived values | lag/lead, percentiles, ROLLUP/CUBE, LISTAGG, sliding frames, time-bucket summaries |
| C09 | Typed expressions | native-qualified (partial) | Closed arithmetic, text, conditional and date functions; named conditions with three-valued logic; no authored SQL fragments | Subqueries, multi-branch CASE (compose by naming), formatting/conversion functions |
| C10 | Mutation and reconciliation | native-qualified (partial) | insert/update/delete/merge by primary key with exact row-count expectations, constraint prediction and database enforcement, pre/post-state verification | Existing-table snapshot mutation with ledger idempotency is qualified, including prospective scale-loss refusal; RETURNING, bulk error handling, deferred constraints |
| C11 | Transactions | native-qualified (partial) | Commit, rollback, savepoints, serializable isolation, separate observer connection (uncommitted invisible, post-finish state), commit-outcome-unknown reporting without replay | In-flight cancellation evidence (needs native lifecycle cases), autonomous and distributed transactions |
| C12 | Schema evolution and reusable objects | unimplemented | Creation and run-owned cleanup of the run's own tables only; the earlier replace mode was removed because replacement needs an explicit ownership/precondition contract | ALTER, indexes, sequences, views, plan/apply/verify of bounded changes |
| C13 | LOBs | native-qualified (partial) | CLOB/BLOB source import, typed binds, bounded native handle read, exact JSON/CSV report/load/mutate publication, independent reference and digests | Empty LOBs, NCLOB, BFILE, unbounded streaming |
| C14 | JSON and SQL/JSON | native-qualified (partial) | Native JSON tables, exact canonical text, typed number/text/boolean member/index extraction and relational handoff | Wildcards, transformations, JSON_TABLE, SODA |
| C15 | Named PL/SQL routines | unimplemented | — | Typed call contracts, collections, REF CURSOR, effect declarations (arbitrary anonymous code stays excluded) |
| C16 | Object/collection/XML types | unimplemented (review pending) | — | Assess value and driver support; portable representation |
| C17 | Vector search | unimplemented | — | The selected Free runtime is available and has been observed to accept vector data; typed vector storage, metric/dimension checks and exact nearest-neighbour acceptance are not written (engine feasibility is not adaptor qualification). Thick mode (C22) is likewise unimplemented, not blocked; bounded native JSON is now covered under C14 |
| C18 | Spatial/graph/text | unimplemented (review each) | — | Separate reviews of geometry, property graph and indexed text |
| C19 | AQ/transactional event queues | unimplemented | — | Enqueue/dequeue/acknowledge and rollback semantics; privileges are blockers if absent |
| C20 | Notifications and scheduling | unimplemented (review) | — | Review native notification value and containment |
| C21 | Bulk/async/pooling/tuning/observability | native-qualified (partial) | Array binds, bounded fetch size and result cap, call timeouts | Async, pipelines, pooling, end-to-end trace identifiers, statement-cache evaluation |
| C22 | Thin/Thick and authentication variants | native-qualified (partial: Thin, password only) | Thin mode enforced, Thick refused | Thick-only features, wallets, TLS, OS/Kerberos/token authentication — need review per capability |
| C23 | Administrative and privileged operations | proposed exclusion (partial) | — | Startup/shutdown, users/grants, backup/recovery, storage, cluster/failover/sharding and distributed coordination are privileged, destructive or multi-server. Non-privileged work on the connected schema (EXPLAIN PLAN, statistics on one's own tables, session tracing) is not part of the proposed exclusion and is to be reviewed subfamily by subfamily |
| C24 | Other Oracle products | documented product boundary | — | APEX, ORDS applications, OCI account/resource administration, ERP/Java, external AI services are separate products, not evidence of Database API coverage |

### Implemented workflow surface (second denominator)

Four operations share one set of records (`inspect`, `load`, `report`, `mutate`):

| Operation | Families touched | Independent verification |
| --- | --- | --- |
| `inspect` | C01, C02, C03 | Two fresh sessions agree; declared tables compared column-by-column |
| `load` | C01–C05 | Fresh-connection dictionary and row readback against captured rows |
| `report` | C03, C05–C09, C21 | Decimal/datetime/three-valued-logic relational reference over the same rows |
| `mutate` | C03, C04, C10, C11 | Step-by-step simulation, observer sessions, fresh readback, constraint prediction |

## Residual API index

Public python-oracledb and SQL capabilities that are not yet classified into a family above, so
that the denominator does not silently shrink: connection pools and session callbacks;
asynchronous connections and pipelines; `callproc`/`callfunc` and implicit results; scrollable
cursors; array-DML row counts and batch errors; `executemany` direct-path loading; end-to-end
metrics (`action`, `module`, `client_identifier`, `dbop`); two-phase commit APIs; SODA;
database objects and `gettype`; sparse and binary vectors; Advanced Queuing APIs; continuous
query and change notification; statement cache and fetch tuning; Oracle Net configuration
(wallets, connection descriptors, proxy and redirection); SQL features such as recursive
subqueries, pivot, model, match-recognize, hierarchical queries and flashback queries; the
dictionary views outside the user catalogue.

## Strength estimates

These are subjective editorial estimates, rounded to five percentage points, not measured API
coverage. They follow the [assessment rubric](../adaptor-assessments.md); the adaptor-owned
record is `src/schemaxis/adaptors/oracle/assessment.json`.

| Dimension | Estimate | Rationale | Source and date | Confidence |
| --- | --- | --- | --- | --- |
| Whole-application breadth | about 30% | Relational and bounded document workflows cover parts of the retained 24-family denominator; PL/SQL, advanced types, vector, AQ and schema evolution remain absent; bounded LOB/JSON workflows have been added | This map, 3 November 2026 | low |
| Abstraction within the declared workflows | about 75% | Shared table, operand, condition, measure and step records replace SQL and cursor handling, with explicit policies; users still choose keys, joins and conditions | This map and the guide, 2 November 2026 | low |
| Native evidence | bounded | Real Thin/Free acceptance, changed-source and adverse/tamper controls | 3 November 2026 verification note | medium |

## Design decisions

* **No nested expression trees.** The declaration grammar is closed and non-recursive, so values
  and conditions are *named steps* in order (`computed`, `conditions`, `measures`) that later
  operands refer to. This keeps schemas, forms, validation, SQL generation and the reference
  evaluator bounded, and it makes the evaluation order explicit.
* **Trusted SQL only.** Literals are bound values; the single inline-literal case, CHECK
  constraint text, uses the same escaping function and is revalidated by the worker, which also
  refuses any statement that does not match a generated shape for its step kind.
* **Independent reference.** The host evaluates the plan over exact Python values; it does not
  share the SQL generator, so a generator error cannot make a result self-consistent.
* **Honest outcomes.** Ambiguous order, unverifiable values (non-ASCII case mapping, fractional
  days), lossy numbers and unknown commit outcomes are refused or reported, not guessed.
* **Reuse.** The same table records serve `inspect` (expected schema), `load`, `report`
  (including `external` existing tables) and `mutate`, and workflows can reuse them with
  document references.

## Open review items

* The observed driver/server identity is recorded above and in each receipt; upstream absorption covers the bounded Thin/Free scope. Other editions and licensed features remain unqualified.
* Check-constraint text is compared by count only; whether to parse the stored expression is
  undecided.
* Existing-table mutation uses an observed snapshot base, complete declared schema, pre-DML mechanism checks, prospective/precommit verification and an idempotency ledger. Privileged concurrent DDL is outside that effect contract.
* An independent reviewer should try authoring a new variant from discovery and guidance alone.

## Pending refinements to implemented families (not exclusions)

* C03 NUMBER: negative scales and scales larger than the precision are not accepted yet and need
  exact quantisation and overflow controls. Native FLOAT/BINARY_DOUBLE/BINARY_FLOAT, intervals,
  national and long text, and ROWID are unassessed.
* C03 text: `varchar2` is capped at 1000 characters so that the 4000-byte limit holds for any
  character; a byte-aware validator would allow longer ASCII text. The refusal of NUL characters and of
  the text `\N` is an adaptor portability policy (JSON/CSV tooling and the CSV null token), not an
  Oracle storage limit, and it narrows the values that can be loaded.
* C09 text functions: Oracle `UPPER`/`LOWER` and Python case mapping differ for some Unicode text
  (for example sharp s and dotted capital I), so the host reference verifies case conversion for ASCII
  text only and refuses anything else rather than guess; a wider verified subset needs an explicit,
  tested policy.
* C02/C04 identifiers: the 24-character lower-case grammar is conservative. Longer and mixed-case
  names, stable hashed constraint names and the preservation of existing quoted mixed-case objects
  need design and native evidence.
* C09 subqueries, common table expressions and correlated queries are not implemented.
* C12 indexes, sequences, views and migrations; C13 streaming/empty LOBs and NCLOB/BFILE; C14 advanced SQL/JSON and SODA; C15 typed routines; C16 object,
  collection and XML types; C17 vectors; C18 spatial, graph and text; C19 queues remain to be
  implemented and qualified, or concretely blocked.

## Live state and replay

A live database's rows and schema are not part of any input digest, so the route registers no
reuse hook and every execution re-runs. A rerun starts from captured sources and refuses when its
table names are taken, so it cannot silently re-apply effects to a retained table, but that is a
refusal, not a retry policy: retained loads still refuse an occupied name; mutations of existing tables use the declared
idempotency ledger and live verification instead of drop-and-recreate. Each run binds its own ownership marker, and
scratch tables use run-unique physical names (native-qualified), so two jobs can stage the same
logical table at once; retained tables keep declared names and a taken name is refused. Changing
pre-existing tables is now implemented and boundedly qualified: serializable base read, database enforcement and an
idempotency ledger checked and recorded in the same transaction; prospective assignments and precommit native state are independently checked. An SCN/flashback comparison and bulk-change ergonomics remain pending.

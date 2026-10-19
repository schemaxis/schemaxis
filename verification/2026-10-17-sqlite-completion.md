# SQLite completion review — 17 October 2026

Initial bounded `schemaxis.sqlite/1` / `summarise`. Responsible owner D03,
GPT-6.1 Sol; root reviewed the relational design, implementation, native quoting,
process isolation and independent verification. No commits or publication.

## Useful scope and runtime basis

The route imports captured typed related JSON tables into a fresh STRICT database,
enforces declared primary/foreign keys, follows one FK inner join, optionally
filters an integer minimum, then publishes ordered group COUNT/SUM plus database,
schema, typed JSON and explicit-null CSV. This supports reproducible regional
sales summaries and similar bounded relational reports without authored SQL.

The latest stable official download and release log were checked on 17 October:
**SQLite 3.54.1**, released 16 October 2026. CLI observed:
`3.54.1 2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76 (64-bit)`.
The official Linux x64 portable archive SHA3-256 matched
`555635de98534d87a67ee2e6e1b0d79f494b1b33b223477d3e7a8ea0c66e416f`.
The runtime is isolated ignored evidence; no global install, spending or PATH change.
Official public CLI, STRICT, SELECT, aggregate, foreign-key and PRAGMA sources
were opened and reviewed; links and mapping are retained in the guide/readiness.

## Completion checklist

| Checklist | Scope and observed evidence |
| --- | --- |
| registration | Root-approved manifest activation. One document route, host-safe declarations, isolated serial runtime, explicit optional-feature decisions, query/reuse/resources hooks. Ordinary discovery succeeds. |
| schema | Complete literal/authored schema derives from declarations for all nested table/column/key/join/filter/group fields. Host conformance passes every valid/invalid example, immutable deterministic planning, defaults and undeclared-field rejection. |
| semantics | Exact INTEGER/TEXT/null rules, no bool/float coercion, duplicate JSON-key rejection, primary/FK integrity, earlier same-type parent keys, qualified active columns, one nonexpanding FK inner join, deterministic binary order and resource caps. Eight host tests pass, including maximum exact integer sum and null/numeric grouping. |
| native-mapping | Real 3.54.1 CLI version/import/read-only-query processes use trusted quoted SQL. Native schema and every typed row are independently reopened. Actual SQL-like quoted TEXT and dot-command TEXT remain literal data; a poisoned default startup file is ignored. Version check precedes imports. |
| execution | Four baseline/variant/empty/single-table cases pass through normal execution/verification with shared schema evidence. Native submissions, exact commands, launcher source, input hashes/stdout/stderr and immutable source captures retained. 15 hostile evidence mutations rejected, including refreshed receipt hashes and altered native DB/capture bindings. Timeout, prelaunch cancellation and real in-flight process-group timeout/cancel pass; owned children are gone. |
| discovery | Reviewed synonym group totals, multiword foreign key, ambiguous table and negative arbitrary SQL console cases cover CLI capabilities, adaptor selection, Add and Help. Actual host capability matching passes; Production Studio selection/Add/Help search suite passes 105/105 including every SQLite case and its contextual operation Help. No suitability ranking is claimed. |
| guidance | Operation plus every nested literal schema address has authored conceptual meaning, defaults, null/key/filter/order/precision/path ownership and mistakes. `studio_guidance.py --app sqlite --check`: 30 reviewed, zero pending/stale. |
| help | Complete local guide with official API references, recovery and qualification bounds. Root owns generated operation reference and packaged contextual Help. Root generated the operation reference and packaged Help; explicit `readiness --app sqlite --admission --check` passes. |
| examples | Sales baseline, changed threshold, empty query, no-join, invalid non-key join and a verified-value workflow example; editable Studio sales/single-table starters. Acceptance expected rows are literal, not derived from producer summaries. |
| tests | Eight host tests pass; reusable host conformance passes. Native recipe `tools/qualify_sqlite.py` runs four kit cases, raw native literal rows, SQL/startup safety, null/zero groups, maximum total, hostile tamper, verified workflow handoff/reuse/source edits, finite composition and lifecycle. Exact results retained below. |
| qualification | Bounded native acceptance is observed. Final normal native conformance and full qualifier passed and registered `qualification.json` at source digest `sha256:b4c3a55bd9e1021890963bd50866b135d5dcfb97faa1fa563311b37f8973ecc8`, recorded 2026-10-17T23:33:08Z. Later shared source changes may conservatively stale this receipt; root will refresh at final batch integration. Old receipts are never labelled current. |
| maintenance | `upstream.json` records official latest stable 3.54.1, release source, absorbed bounded scope and exact requalification obligations. Other native versions/platforms require qualification. |

## Retained verification

Bulk local evidence is under ignored `evidence/programme-20261017/sqlite-*`.
`sqlite-acceptance-02/acceptance.json` reports all checks verified, including four
kit cases, 15 hostile probes, SQL/dotcommand literal safety, poisoned startup,
true verified numeric handoff, unchanged reuse, same-path byte-edit invalidation,
two composed states and in-flight timeout/cancel. `sqlite-acceptance-final/acceptance.json` confirms the full final suite and registers the current receipt. `sqlite-acceptance-03` adds actual
native null-versus-zero grouping and maximum 2048-row integer total
**2048000000000**, checked in raw CLI JSON as an integer. The fixture combines null
FK omission, signed totals, zero, empty text and all-null groups; empty query emits
headers and zero rows rather than inventing a group.

Commands executed:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_sqlite.py -v
PYTHONPATH=src python3 tools/studio_guidance.py --app sqlite --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.sqlite/1 --output-directory <fresh-host-evidence>
PYTHONPATH=src python3 tools/qualify_sqlite.py --sqlite <isolated-official-cli> --output-directory <fresh-native-evidence>
```

The original sources are not read during verification: captured bytes, declarations,
raw native rows and independent database reopen establish each result. Workflow
reuse hashes current source bytes so same-path changes invalidate reuse. Shared
schemas use the framework boundary automatically; no parallel app store exists.

## Limits and legitimate exclusions

Native evidence covers Linux x64 SQLite 3.54.1 with POSIX process/resource isolation;
host planning remains Python 3.10+ dependency-free. It does not qualify arbitrary
SQL, decimals/floats, Unicode text, dates/blobs, unit conversion, left/many-to-many
joins, existing database mutation, network, extensions, MPI, time batches, native
inspection or live reverse editing. Native save means a fresh checked database.

Native CPU 30 s, address space 512 MiB, per-file 16 MiB caps apply to each child;
a total configurable deadline covers all stages and final verification. Sources
are at most 1 MiB/table; retained reads at most 8 MiB; 1–4 tables, 0–2048 rows,
1–12 columns and 1–3 group keys bound host/native work. Numeric exactness follows
from integer cells within ±1000000000 and the nonexpanding join; totals have a
separate ±2^53 interchange guard, well above the current maximum possible sum.

Native launchers and command/input binding records contain absolute run paths.
Relocating an evidence directory invalidates those bindings; the schema store's
portable export capability does not establish native receipt relocation. Keep
native evidence at its recorded path, or run a new captured workflow at the new
location. CSV null is the reserved literal `\N`; empty text and zero remain values.
Inspection certifies bounded data/SQL semantics, not all SQLite functionality.

Scoped Studio starter planning and nested placeholder reporting pass in the eight
SQLite unit tests. Shared Node operation-form regression passes 3/3. An additional
whole-catalogue test encountered three unrelated pending ImageMagick templates
whose document route had not yet been activated; SQLite templates passed. This
concurrent-integration limitation was reported to root, not hidden or repaired by
loosening the test. A mistaken request for non-existent `forms.test.mjs` was
corrected to the actual `operation-form.test.mjs` and passed.

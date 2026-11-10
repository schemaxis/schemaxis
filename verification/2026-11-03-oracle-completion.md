# Oracle relational and document workflows — 3 November 2026

The supported product scope is inspection, typed loading, relational/document reports
and atomic mutation, including existing-table idempotency. This is not full Oracle
Database coverage. The [24-family inventory](../docs/design/oracle-coverage.md) retains
schema evolution, PL/SQL, advanced types, vector, spatial/graph/text, queues, advanced
session/authentication and administrative gaps.

The source adds bounded CLOB/BLOB values and native JSON to the shared table contract,
with exact canonical JSON and closed member/index scalar extraction. Discovery,
schemas, forms, conceptual guidance, examples and readiness use the same declarations.
The host remains dependency-free; python-oracledb is imported only in a native worker.

## Review controls

The inherited review of the earlier implementation identified the following defects.
This table names the concrete controls and their evidence rather than carrying forward
its old unqualified claims. Current independent review remains an integration step.

| Finding | Current control and evidence |
| --- | --- |
| B1: test doubles escaped their patch | Each host action holds the execute patch throughout execution; test setup forbids subprocess and network effects. Dedicated worker protocol tests use explicit driver doubles. |
| B2: division/average decoding | Separate 40-digit computed-result and 38-digit stored-NUMBER codecs; independent 40-digit reference with documented comparison tolerance. Native qualifier checks divide/average, host tests check 1/3, 2/3, overflow and ambient Decimal context. |
| B3: assignments could commit before scale-loss refusal | Target-column codecs check literal and derived assignments. Every mutation now reads its base in the apply transaction, runs the prospective reference before DML, and compares uncommitted native rows with that reference before COMMIT. External 75 minus 0.015 refuses with unchanged 75 and no ledger row. A post-work fault reports databaseTouched=true and its completed outcome. |
| B4: cross-run destructive cleanup | No replacement mode. Run-unique scratch names and exact per-run markers; cleanup only uses completed/journalled creates whose exact marker still matches. External objects receive no DDL. Unknown outcomes preserve tables. Native qualification performs marker-bound cleanup and checks remaining objects; host tests exercise name mapping and wrong-marker cases. |
| B5: qualification/metadata | Full native acceptance is required, with compact observed runtime results below. Assessment fingerprint is refreshed. Shared generated Help/reference and final receipt registration belong to integration and are not claimed by this branch. |
| H1: credential-scan waivers | Short secrets refuse before work. All retained files, including final status and failure output, are scanned in UTF-8/16, escaped, percent and base64 forms; leaking files are blanked and a structured leak fault replaces the prior failure. Host adversarial tests and native wrong-password/unreachable-profile cases exercise this. |
| H2: destructive replace | Removed from grammar and execution. A taken retained name refuses before apply; native qualifier checks that existing rows survive. |
| H3: intermediate/unknown commits | Seed and final commits both use unknown-outcome handling. Synced before/after DDL/control journals survive worker termination, report possible orphans, and prevent unknown-outcome cleanup or replay. Unit protocol controls inject commit-reply loss; native timeout/cancellation use actual workers. No real network-partition claim is made. |
| H4: external schema drift | Generated key names are included, VARCHAR2 BYTE semantics remain distinct, read-only external column subsets are allowed. Native external readback and existing mutation exercise ordinary database-generated keys. |
| H5: report snapshot | External base rows and report execute within one query-only SERIALIZABLE transaction. READ ONLY is intentionally avoided after fresh DDL because the observed server rejects it with ORA-01466. Native/source tests enforce the read-only generated-step surface. No flashback/SCN or multi-server snapshot claim is made. |
| H6: native ordering | Native sequence is checked against declared direction/NULL placement before canonical tie settlement. Host reversed-native-row control must fail; native baseline/variant/offset/window cases retain literal expected outputs. |

Oracle itself documents that serializable transactions do not support deferred segment
creation. New adaptor-created tables request immediate creation. A fresh external
ledger instead produces ORACLE_SERIALIZATION_CONFLICT (ORA-08177), with independently
verified rollback and no automatic replay. This is separate from business idempotency.

## Evidence and limits

Initial newly run controls: 159 Oracle host tests passed; the independent seven-case
existing-table native probe passed commit, replay, conflict, rollback, row count,
scale-loss and subsequent commit. An actual document report passed with python-oracledb
26.1.0 Thin / Oracle Database 23.26.3.0.0, including supplementary Unicode CLOB,
BLOB, native JSON and typed scalar extraction. These exploratory observations are not
substitutes for the final source-current qualifier.

The full public native qualifier completed successfully with 67 run directories,
nine shared readiness cases and successful timeout/cancellation controls, plus nine
literal relational matrix cases (set operations, distinct, offset, running windows,
RAW and BOOLEAN). The
observed runtime was python-oracledb 26.1.0 Thin / Oracle AI Database 26ai Free
23.26.3.0.0, AL32UTF8. All eight existing-table cases passed, including the
75 minus 0.015 refusal before DML and unchanged ledger, and fresh deferred-ledger
ORA-08177 with verified rollback. Document load/external-read/mutation, seven
mixed-shape JSON positives, two pre-native type/multi-match refusals, changed
source and three refreshed-digest tamper controls passed. Final credential scan
passed and the owned server was stopped. Receipts remain private and unregistered
until shared generation and final integration checks.
The qualifier includes shared readiness/lifecycle cases, exact values, relational
variants, transaction outcomes, external idempotency, deferred-segment refusal,
changed document source, and refreshed-digest publication/native/readback tampering.
No native skip counts as completion. Run directories and machine configuration remain
private; no credentials, workstation paths or private transcript are committed.

Verification checks internal consistency of captured sources, trusted programs,
native results and publications. It is not a signature proving the authenticity of
an entirely forged directory. Final qualification registration and source identity
must be assessed separately from portable saved-run verification.

Mixed-shape JSON paths and Boolean-string conversion were independently probed
on the real engine. The reference implements the observed closed lax semantics;
multi-match scalar paths and numeric-to-Boolean extraction refuse before native
work for captured sources. Lone-surrogate JSON text produces a structured fault.

The external mutation effect boundary additionally checks schema metadata before
reading base rows or sending DML: enabled triggers, virtual/default columns,
function/domain indexes, row policies, cross-user REFERENCES grants and undeclared
incoming CASCADE/SET NULL children refuse. Mutation declarations must include the
complete target schema, while read-only reports retain column-subset support.
The public native qualifier includes a VALID autonomous audit trigger and both
incoming delete actions, asserting account/ledger/audit/child state is unchanged
on refusal; a read-only report with that trigger must still succeed. Privileged
concurrent DDL is outside this declared-schema contract.

Final source-current acceptance also passed the autonomous-trigger and undeclared
CASCADE/SET NULL native controls described above. The disposable schema initially
lacked CREATE TRIGGER; fixture qualification temporarily granted it through a
local administrative connection and revoked it in finally. The post-run audit
found no residual schema objects, and the owned server was stopped. The failed
unprovisioned fixture attempt is not counted as a successful native case.

Host conformance, 159 Oracle tests, 201 reviewed conceptual guidance records
(0 pending/stale), the current assessment fingerprint, `git diff --check` and the
unmodified release gate passed. Whole-application breadth remains an editorial
30%, supported-workflow abstraction 75%; neither percentage measures API coverage.
Shared Help/reference generation and final registered receipt freshness remain
integration work and are not claimed by this branch.


## Post-completion and credential fault review follow-up

A later independent review found that final publication cancellation/deadline and
other host failures bypassed completed-outcome annotation, and that credential
scan faults echoed leaking filenames into an unscanned final fallback. These are
repaired centrally. Durable finish facts are cached and recovered from completed
partial/journal finish records; readback, analysis, publication, verification,
scans, final gates and status I/O preserve committed/rolled-back/unknown facts.
A successful empty-session rollback after a committed finish is distinguished
from rolling the mutation back. Inspect has a read-only outcome and needs no setup.

Scan faults now use ordinal IDs, empty leaking contents, redact dynamic fault
values, and scan the replacement failure status with a bounded retry. Stable fault
codes/keys remain intact; credentials colliding with public protocol vocabulary
refuse before creating run files or touching Oracle. Such a value can inherently
coincide with a mandatory public JSON key in a structured refusal; it is an
unsupported configuration, never a post-native scan waiver.

Focused host controls cover cancellation, deadline, readback, analysis,
verification, publication and status I/O, final-status scan failure, a post-finish
observer refusal, journalled finish after worker loss, unknown-state preservation,
PASSWORD equal to result.json, and protocol-identifier collisions. Native worker
code is unchanged; final integrated native publication-failure proof is performed
by the integration owner rather than claiming that the earlier 67-run receipt
remains current after this host source change.


The follow-up recheck also reserves required outcome/status values before native
work, including `committed`, `rolledBack`, read-only/seed labels and status values;
substring collisions are refused. The exact `committed` credential reproduction
now refuses before creating run files, while the ordinary post-commit cancellation
control retains outcome `committed`.

Acknowledged load/report seed commits are recovered from partial records and synced
journals. A later failed report preserves the durable seed rows but explicitly
records report work as incomplete, rather than claiming the whole database work
completed or the committed seed was rolled back. The expanded Oracle host suite
passes 174 tests, including partial report failure and journalled load seed commit.
No native worker code changed in this follow-up.

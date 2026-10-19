# Code quality and technical debt audit

17 October 2026. Scope: shared runtime, registry, schema/storage, Studio recovery,
workflow execution and representative adaptor boundaries. This is an evidenced
improvement plan, not a repository-wide refactor or a claim about authorship.

## What is working well

Manifest discovery keeps application names out of core dispatch. Host planning
and native subprocess execution have a useful boundary; common studies preserve
state/evidence identity and verify each transition. Structured faults, immutable
attempt directories, atomic/fsync publication, captured inputs and independent
artifact checks provide a strong basis. Existing tests exercise corruption,
timeout/cancellation, stale plans and semantic outcomes, not just successful
exit. The 16 October review documents real numerical and evidence corrections;
those historical checks are not automatically qualification of today's source.

## Prioritised findings

| Priority / scope | Evidence and consequence | Proposed action | Benefit, risk and effort | Verification |
| --- | --- | --- | --- | --- |
| P1 focused correctness: recovery uses removable assertions | `console_session.AdaptorConsoleSession._validate_state` uses `assert` for document membership, revision bounds, source/document equality and configuration types. A disposable direct probe of an empty document map with absent active identity is rejected normally but accepted under `python -O`. Checksummed data can still be structurally wrong; a checksum is not schema validation. | Replace data-validation assertions with explicit condition checks and stable `RECOVERY_FAILED`; validate container types before indexing. This audit records the issue; it is not silently fixed as an unrelated storage refactor. | High correctness benefit; low/moderate implementation risk, small effort. | Run malformed but correctly checksummed session fixtures under normal and optimised Python; identical rejection and lock-release behaviour. |
| P1 architectural prerequisite: storage ownership/liveness incomplete | `configuration.py` records paths only; no installation ownership, dependencies or last-use counts. Coordinators/session use advisory locks, but all native/legacy paths do not share a durable run lifecycle ledger. Inferring managed ownership or inactivity from age risks unsafe deletion. | Define a managed-install receipt and run lease/completion contract before generic uninstall/source-pruning. Keep current inspection/backup operations non-destructive. | Unlocks requested safe management; medium/high design risk/effort. | Active/restarted/crashed owner tests, shared dependency graph, external installations never claimed, stale plan rejection, verified backup before explicit removal. |
| P1 portability: absolute paths in receipts | `parallel.verify` compares recorded attempt directories with absolute current paths; adaptor receipts and captured input provenance frequently retain absolute files. A relocated byte-complete backup may fail native verification. | Specify a future evidence envelope with relative internal member paths and separately declared external dependencies; version it and preserve old readers. | High value for sharing/archive; high compatibility risk and effort. | Restore at original/new root without rewriting historical hashes; independent native checks and workflow reuse; missing external dependency diagnostics. |
| P2 evidence portability: retained workflow verification reads live sources | `parallel.verify` calls `reusable_inputs(effective)` and compares current external input hashes with the saved job. A native SoX probe could verify its standalone captured attempt after removing the disposable original, but could not verify the enclosing scheduled workflow. Resume freshness and retained-capture integrity currently share a live-source check. | Define an adaptor-owned retained-input binding contract for historical verification, separately from live-source hashing for resume. Do not simply remove the comparison: the saved job's hashes must remain bound to verified captured inputs. Until then, document that workflow verification needs unchanged original sources. | Enables useful archival without losing source binding; medium/high cross-adaptor compatibility risk and effort. | Missing/changed original still permits historical verification when capture bindings are intact; resume invalidates changed live inputs; forged capture/job hashes and uncaptured external dependencies still fail. |
| P2 storage/CPU: runtime package contains host documentation | `artifacts.runtime_archive` recursively includes all `.py/.json/.txt` under the core/package trees. Measured archive includes ~5.17 MB compressed Help/guidance of ~7.18 MB total. Every source resource change can alter that bundle. | Audit actual native imports/resources; design native-minimal versus full-reproducibility bundles and exact bundle reuse. Keep full source provenance accessible. | Large storage and launch benefit; medium/high plugin compatibility risk; medium effort. | Native route/plugin tests on reduced bundle, notices/resources retained, stale cache and interrupted publication probes. |
| P2 latency/storage: full undo history rewrite | `authoring.replace` deep-copies state and appends a complete document/source snapshot; `console_session._commit` encodes and fsyncs the entire state. Source is bounded to 1 MiB, but history length is not bounded there. Repeated large edits can grow serialization and recovery costs. | Benchmark large real sessions, then propose immutable content snapshots plus a small revision journal and periodic checkpoints. Do not silently truncate undo. | Potential high benefit for long sessions; high recovery complexity; high effort. | Crash/recovery and undo semantics, invalid source preservation, actual sizes/timings before and after. |
| P2 integration cost: conservative qualification source digest | `adaptor_delivery.source_digest` excludes other adaptor directories but still traverses shared Studio Help/resources and core source. Unrelated generated Help can invalidate otherwise unchanged adaptor receipts; the previous Help/receipt cycle was correctly fixed. | Keep current conservative correctness. Investigate explicit tested dependency sets or separate host/UI/native digests rather than weakening checks ad hoc. | Less unnecessary native requalification; high false-freshness risk; medium/high effort. | Change every relevant native/shared dependency and require staleness; prove unrelated documentation-only change cannot falsely qualify native code. |
| P2 clarity: dense app-specific verifiers and duplicate process scaffolding | `adaptors/ffmpeg/adaptor.py`, `qgis/adaptor.py` and `octave/adaptor.py` compress validation/evidence mutations into semicolon-heavy lines. Multiple adaptors repeat input capture, native launch, reopen and manifest logic with subtle differences. Raw line count is not the finding: error boundaries and evidence assumptions are harder to inspect. | During useful adaptor improvements, expand touched dense sections and extract only demonstrated common capture/receipt helpers with explicit policy hooks. Do not create a new universal native wrapper for unlike applications. | Better reviewability and fewer drift bugs; moderate risk if verification policies are merged; medium effort. | Existing exact fault, forged-output, timeout and native checks; preserve application-specific independence/tolerances. |
| P2 documentation drift | `docs/adaptor-runtime.md` still states thirteen adaptors/fifteen routes despite the initial twenty-app inventory. Historical `docs/design` audits and current capabilities are easy to confuse. | Derive counts from the manifest registry in generation checks, clearly date historical reports and separate shipped scope from candidates. | Better user/agent decisions; low risk, small effort. | Reference freshness and linked-scope checks; avoid a second registry in prose. |
| P3 durable usability: case job catalogue is process-local | `studio_cases.StudioCases.records` starts empty; case output files survive but the HTTP job identity lookup does not rebuild them at restart. | Add a validated read-only run index/reconciliation first, then attach persisted job metadata to it. | Better return-to-project workflow and storage inventory; moderate compatibility/liveness design, medium effort. | Restart with completed/failed/interrupted jobs, moved/missing directories, tampered metadata and duplicate IDs. |

Broad `except Exception` blocks were inspected in registry isolation and owner
cleanup paths. They are not automatically defects: plugin exclusion and failure
retention need an outer boundary. Future work should preserve the underlying
structured fault/trace and distinguish expected errors; deleting those boundaries
would reduce robustness. Likewise, workflow repetition in independent verifiers
can be intentional separation, not waste to remove indiscriminately.

## Changes made by the current programme

Shared schema captures are being integrated at the common run/study/workflow and
Studio checkpoint boundaries, retaining legacy exact-byte snapshots. New storage
management uses explicit selections, reviewed immutable plans, conservative
shared-data protection and verified copies/archives. CLI version/help discovery
and documented headless checks address real usability gaps. These changes are
reviewed separately; their presence does not resolve the architectural ownership,
full evidence relocation or history-journalling findings above.

Recommended order: finish and review the bounded storage/CLI/adaptor work; address
explicit recovery validation with focused tests; design ownership/liveness and
run indexing together; then evaluate runtime deduplication and session journalling
against measurements. Broader format changes require migration/compatibility
review and remain proposals.

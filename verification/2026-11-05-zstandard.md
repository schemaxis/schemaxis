# Zstandard adaptor — accepted stable CLI baseline

The fixed native baseline is Zstandard 1.5.7. Official release, CLI manual and
compression-format specification were reviewed before implementation. This note
preserves the development history below; the final section records engineering
acceptance for that baseline. No public release or version bump is approved.

Twelve typed tasks cover compression, restoration, frame inspection, dictionary
training and inspection, reference deltas, complete-frame concatenation, profile
comparison, native compression/decode benchmarks and captured file sets.
The independent host reader parses frame boundaries, headers, block sizes,
dictionary identities and XXH64 content checksums. Fresh native decoding compares
actual bytes with retained inputs; deterministic compression and dictionary
training are reconstructed to bind requested controls that are absent from frame
headers. Historical command receipts do not select the verifier executable.

Initial native checks passed all five built-in format paths: Zstandard, gzip,
xz, lzma and lz4. The subsequent control/family run passed 17 host checks and
native dictionary training/use, checksum-free chunking with fast mode, delta
encoding, concatenation, profile comparison, restoration and inspection.

The first dictionary probe failed because a corpus fraction was passed directly
to the CLI's integer-percentage `split` parameter. The failure was retained;
the mapping now converts 0.75 to 75, validates whole-percent precision and requires
at least five training samples. The repaired native family run passed.

Producer wall time is an observation, not a result that later verification can
authenticate. The profile summary explicitly records `timingVerified: false`.
Compressed content and sizes are checked independently of that timing claim.

The original seven-task frozen qualifier passed all five codecs, all three
training algorithms with separate held-out records, unknown-size chunks,
literal hand-written raw/skippable frames, delta restoration, four refreshed-hash
attacks, source-path removal and workflow reuse/invalidation/damage rebuild.
Initial failures exposed an unsuitable compression-policy corpus and then a
chunk-count budget; both failed rounds were retained and the fixture repaired.

Independent review reproduced three further defects: concatenation decoded all
inputs before enforcing its aggregate limit, valid skippable-only input was
refused, and restoration admitted conflicting dictionary/reference dependencies.
These were repaired. Known/unknown-size aggregate limit probes now pass at
1800 bytes and refuse 1000/1799-byte budgets. Unknown-size overflow initially
returned a generic native fault after sparse output failure; actual output caps
and native EFBIG diagnostics now retain the structured budget diagnosis.

Extended development probes passed raw dictionaries, omitted/pledged/hinted
content size, approximate block targets, adaptive compression, worker history,
long-distance tables and Cover shrink/training level/sample blocks. Native
benchmark whole/block/decode probes check sizes through separately created CLI
frames. The first benchmark parser incorrectly expected an untruncated capture
name; official 1.5.7 source establishes its last-17-character display policy.
External dictionary inspection passed all three trained dictionaries and raw
history; an invalid eight-byte trained header was refused by native loading.
Recursive file-set probes passed all five codecs, nested/empty files, exact
restoration, original-directory removal and named/chunked/fast composition.

Host checks and schema/planner conformance pass; guidance covers 238 field
addresses plus 12 task records without pending/stale entries. Actual Studio
authoring checks the all-types file chooser, typed level and nested adaptive
edits, validation and atomic undo. Earlier browser-test failures included
invalid search-case slug IDs (repaired), an incorrect expectation of a pipeline
Add control for a direct-document route, and a test selector quoting error.

Still required: frozen extended native acceptance, complete installed-product
discovery/Help/authoring, independent whole-inventory review, coherent shared
generation, exact integrated source qualification and package acceptance. The
extended probes are development evidence until those gates pass. No absorbed
upstream version or whole-adaptor acceptance is registered prematurely.


## Repaired extended checkpoint and delivery review

The repaired twelve-task frozen run at `ee11b24` passed all original cases,
19 extended checks and 18 file-set checks. Independent review first reproduced
three further defects: excluded ancestor directories could enter a forged
retained selection, long output names could fail after native work, and some
strategy controls were ignored or clamped by upstream. The repair uses one
ancestor predicate for live and retained selection, admits UTF-8 and actual
filesystem limits before capture, and requires an explicitly effective strategy.
The independent recheck passed the old attack, name-boundary controls and actual
native minimum-match variants. Shared publication metadata also preserves opaque
restored CSV bytes and refuses output/staging collisions.

The public registry successfully publishes the longest admitted leaf name and
restores opaque `.csv`, `.json` and `.txt` content as file artifacts. Thirty-nine
focused host checks pass. Twelve guided task selectors now project into Studio's
Add catalogue from the same closed discriminator used by schema validation;
all twelve starters, all-types browsing, typed nested edits and undo pass in the
actual browser. Changing a task still requires reviewing its relevant inputs.

| Checklist item | Evidence and remaining decision |
| --- | --- |
| registration | One registry-discovered process adaptor and composed/scheduled document route; no native imports in discovery. |
| schema | Closed task alternatives, typed nested choices, immutable planning and exact-fault invalid examples; a root discriminator projects task selection without weakening branch membership. |
| semantics | Captured regular inputs, relevant controls, strategy-specific admission, collision-safe relative names and aggregate/decode/window budgets checked before native use. |
| native mapping | Zstandard 1.5.7 tagged CLI, format and benchmark sources; fixed process arguments and fresh readback of content/frame policy. Adaptive schedules and historical timing remain observational. |
| execution | Trusted configured executable, one deadline, cancellation, isolated bounded processes, exact retained inputs and fresh verification; source removal and workflow reuse/invalidation/damage controls pass. |
| discovery | Curated task purposes and phrases, closed task selectors and named Studio starters; current installed discovery acceptance remains required. |
| guidance | 238 attributed field records and 12 task records, zero pending/stale entries; expert controls explain units, defaults and ineffective combinations. |
| Help | Local guide plus generated reference and contextual task/field Help; shared generation and installation must be checked on the integrated source. |
| examples | Literal baseline/variant/invalid documents, all task starters, two independent content corpora, dictionary held-out records and nested file selections. |
| tests | Focused host, actual browser, native lifecycle and adversarial checks pass; exact integrated full host/Studio suites remain a final gate. |
| qualification | Frozen extended native proof is retained by exact source and tool digests; it is historical after source changes and is never relabelled as integrated acceptance. |
| maintenance | Stable tagged upstream sources and repair recipe supplied; no absorbedVersion or release claim before final native and product gates. |

The proposed product boundary covers durable CLI content workflows. It does not
promise library ABI embedding, unlimited live pipe service, native destructive
source removal, OS process priority or a filesystem archive of ownership and
timestamps. Independent inventory review found no further major stable CLI
content family omitted after the listed repairs. That review does not replace
the remaining integrated package, authoring and acceptance gates.

## Pinned workflow input follow-up

Owner source `36d2bcb` adds explicit snapshot consumers for task-specific file
inputs and complete file-set directory roots. Literal/authored schemas and the
consumer policy agree; unrelated controls, wrong-task fields and malformed list
positions remain refused. Files selected from a directory snapshot retain pinned
membership, while a whole-directory reference is accepted only at `fileSet.root`.
The shared contract test now checks paired schema/consumer opt-in for every route
and keeps references absent from routes with no declared policy.

The source-bound follow-up passes 58 host checks and reviewed source guidance.
Actual native workflows restore literal binary bytes, independently decode two
recursively selected files including a Unicode name, verify after original-source
removal and reuse completed jobs. Changed captured bytes are refused before reuse;
restoring them requires an explicit successful resume before workflow verification.
An independent peer source review found no actionable role, pointer or schema
closure defect; that review did not duplicate the native proof.

Initial private harness runs omitted the trusted verification location and then
expected a failed workflow ledger to become successful merely by restoring bytes.
Both failures are retained. The corrected proof supplies explicit trusted
configuration and resumes the workflow after restoration. Its recorded source
digest is `sha256:f52a491785a32b4586bd25199b73dda4abef2ea1e467f8e090fa7b8d9fd007a5`.
Earlier full compression evidence retains its earlier source identity. Final
integrated generation, full suites, package and whole-adaptor acceptance remain
open; this follow-up alone is not a whole-adaptor completion claim.

## Integrated native matrix

The complete native qualifier passes on integrated source `3364b07`, using
Zstandard 1.5.7. Its conservative source digest is
`sha256:f7062a41b221c7b115a509a4e3132cb2de3c182e4ee3e64a00aab289c583fa25`.
The matrix includes all five codecs, advanced matching and scheduling controls,
three dictionary trainers and held-out records, raw dictionaries, reference
deltas, frame joins, native benchmarks, recursive and named file sets, and pinned
adopted files and directories. Literal content expectations, independent decoding,
refreshed-hash mutations and workflow recovery check the resulting content and
dependencies. Observational timing and adaptive level histories retain their
stated limits. This execution is bound to that source; later source changes need
an explicit evidence reconciliation. Complete host, Studio and installed-package
acceptance remain separate gates.

## Final integrated acceptance

The master accepts the independently reviewed durable stable CLI content scope
at integrated code checkpoint `1070354`. All thirteen required inventory families
are verified, with no known required family deferred. This accepts the recorded
Zstandard 1.5.7 baseline, twelve typed tasks and five codec paths. It does not
promise every conceivable workload or compatibility with a future release.

The complete discovered host set contains 5,806 test IDs, each assigned exactly
once across four batches: 5,485 executed and 321 explicitly accounted for by
class/module setup skips. Per-test skip reasons are also retained; unavailable
native tests do not count as native acceptance. There are no failures, errors or
unaccounted tests. Batch zero executed at `6d249a1`; its reuse at `1070354` is
limited to an audited three-file CAD-documentation/generated-Help delta. The
other batches ran at `1070354`; the affected documentation and generation checks
also passed. Earlier failures and interrupted attempts remain historical.

The complete Studio suite at `1070354` passes 914 of 917 tests, with three
explicit skips and no failures, across 71 test files. Its source remained
unchanged. The repaired connection test waits for the existing asynchronous
selection update; its original assertions and deadline are unchanged.

A clean wheel built from `1070354` has SHA256
`61731d1696a67047b7344ccd10556496862b45e9524f5d5ac1383fc1e9e6c770`.
A fresh isolated installation passes discovery, all four programme providers'
starters and bundled Help, native-free host admission, actual Zstandard
round-trip/source-removal verification, and browser authoring from an empty
workspace. Unchanged source and wheel release gates report zero prohibited hits
using 32 patterns, including 26 private patterns. This is a local candidate at
the existing package version, with no publication.

Native execution remains bound to `3364b07` and the digest above. A byte-for-byte
reconciliation confirms that every Zstandard provider file, shared Python
execution file and all four qualification tools are identical at `1070354`.
Later unrelated adaptor repairs, readiness, generated Help, CAD prose and
browser-test changes have their separate current gates. Historical native
receipts are never relabelled as a newer execution. Acceptance-only maintenance
metadata and this note do not change native behaviour.

Independent whole-inventory review compared the tagged upstream manual and
ordinary workflows against the expanded inventory, challenged the abstractions,
and reproduced control and authoring defects. Those defects were repaired and
independently rechecked. All five acceptance questions have satisfactory answers:
no omitted mainstream bounded CLI content family was found; meaningful variants
have typed composable routes; no raw-script fallback is required; the stated
exclusions reflect the product boundary; and no known ordinary supported job
requires a new adaptor implementation project. The master reconciles that
conditional recommendation with the completed native and product gates here.

The accepted boundary excludes libzstd ABI/application embedding, internal
debug/fuzz helpers, unbounded persistent pipes, destructive input removal and
OS-priority aliases. Schemaxis owns capture, process scheduling and fresh
publication. File sets preserve relative names and bytes within their documented
caps, including 32 files, 64 MiB raw and 72 MiB encoded aggregate limits, 4,096
visited entries and 16 path components. They do not archive permissions,
ownership or timestamps. Zstandard CLI has no native MPI family. Adaptive
trajectory and historical timing remain observational, as stated above.

## Guide-status correction and installed recheck

The guide still contained an obsolete development/pending-acceptance paragraph
after the engineering acceptance above. `c9daaa2` corrects that paragraph and
regenerates Help; it also reconciles HDF5 delivery and changes only descriptive
shared conformance-receipt scope wording. Native mapping, assertions, deadlines
and qualification gates are unchanged. The exact descriptive delta, 88 focused
host checks, all four active application guidance/readiness checks, generated
reference/Help/admission parity and unchanged source release gate pass.

A fresh wheel from clean `8b966d0`, SHA256
`87612e72717d9a060b839599085f7f6de79d3a3bd72dae49f14d873e29e021df`, again passes
installed Zstandard round-trip/source-removal verification, discovery, starters,
bundled Help and actual browser authoring, plus the unchanged wheel release gate.
The original full native proof remains bound to `3364b07`; it is not relabelled
as a new execution. The final verification-note-only delta is outside the wheel
and cannot change that installed artifact. The bounded Zstandard engineering
acceptance remains in force, with the same reviewed exclusions and no release.

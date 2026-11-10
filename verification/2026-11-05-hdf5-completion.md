# HDF5 adaptor completion review (2026-11-05)

The fixed runtime baseline is h5py 3.16.0 with HDF5 2.0.0 and NumPy 2.5.4,
on Python 3.14/POSIX. HDF Group h5dump 2.2.0 is the independent format reader.
The separately built parallel runtime uses the same h5py/HDF5 versions,
mpi4py 4.1.2 and Open MPI 4.1.7. The writer is HDF5 2.0.0; the independent
reader version does not change that claim.

The user accepted **local MPI only** for v1. Two- and three-rank read/write
semantics have been qualified on one workstation. Multi-node correctness,
parallelisability and parallel performance/scaling remain important future work
with concrete acceptance criteria in
[the MPI backlog](../docs/design/hdf5-multinode-mpi-backlog.md).
No cluster deployment or scaling result is claimed.

## Current product scope

`schemaxis.hdf5/1` has eight operations: `createFile`, `editFile`, `inspectFile`,
`extractData`, `writeMeshFields`, `appendSeries`, `compareFiles` and `parallelWrite`.
Typed intent covers hierarchical scientific files, storage/access choices,
selection and predicates, compound-field edits, null/scalar/zero-extent datasets,
references and scales, captured dependencies, adoption/repack/comparison,
SWMR acquisition and XDMF/array/table handoffs. It does not accept authored code
or an untyped native-property escape.

| Delivery area | Current evidence and boundary |
| --- | --- |
| Declarations and validation | Strict operation and nested-record schemas, located semantic faults, explicit defaults and budgets; all registered examples and readiness cases checked. |
| Values and storage | Host expectations derive from typed intent, literals, generators and captured inputs; fresh native readings and h5dump check saved bytes. Direct chunk indexes and copyChunks have their own physical-identity checks. |
| Adoption and dependencies | Metadata-only admission precedes data readers; external raw/VDS/link dependencies must be captured with declared roles. Dynamic native filter plugins are disabled. |
| Verification | Fresh readings of current publications and retained source/dependency bytes rebuild inventories, expected state, reports and extracts. Refreshed file hashes do not authorise semantic changes. |
| Discovery and authoring | Curated search, all eight operations and declared fields, Studio starters, conceptual guidance, generated reference and bundled Help are checked through the shared delivery pipeline. |
| Runtime lifecycle | Shared deadlines/cancellation, explicit output publication, fresh reopen, reuse/resume, dependency invalidation, source removal, failure and recovery are exercised. |
| Local MPI | Separate controlled runtime for parallel writes and extraction, with host/serial independent checks and rank receipts; localhost placement is enforced. |
| Maintenance | Fixed versions are recorded in upstream metadata. Subjective breadth/abstraction estimates remain 75%/70%; these scores include the wider application denominator and do not establish acceptance. |

## Source-bound integrated native evidence

Full native qualification at clean integrated commit
`62deeffa556a4bc7fff998bdd64d5c2c11905691` passed **20 cases, 91 tampering/control records and
184 lifecycle, admission, variant, workflow and independent-consumer checks**.
Fixtures were unmodified and the source remained clean. This includes local MPI,
independent NumPy handoff, meshio XDMF and xarray/h5netcdf consumers. Each record
retains its own actual input, runtime, expectation and observed result.

The same integrated checkpoint passed the required full host suite: 5,817 test
IDs accounted for exactly once, 5,496 executed and 321 unavailable-runtime
setup-group skips, with no failures, errors or unaccounted tests. Individual skip
records are retained; skipped native tests are not native acceptance. The full
Studio suite passed 923 of 926 tests, with three explicit skips and no failures.
Generated delivery, all four active application guidance/readiness surfaces and
97 focused integration checks also passed.

An earlier full run was interrupted by an external SIGTERM and is retained as
incomplete, rather than combined with this passing run or labelled successful.
The retry used the same resource limits and assertions. Subsequent descriptive
metadata changes require explicit source-scope reconciliation; they do not become
new native execution evidence by naming a later commit.

## Independent whole-inventory review and repairs

The independent reviewer challenged the fixed-baseline application inventory and
ordinary stable workflows, rather than reviewing only the implementation's listed
operations. No remaining concrete ordinary-use P1/P2 or omitted major stable
file-workflow family was established after the following repairs:

- Unicode, spaces, punctuation and leading-dot internal names remain addressable
  through adoption, extraction, edits, expectations and fresh verification.
- Narrow fields and padded compound records honor the declared streamed-memory
  model; variable-length payloads under memoryBytes have located refusals.
- Integer membership and protected compound siblings retain exact uint64 values,
  including values near the unsigned limit.
- Stored chunk physical identity is checked against a fresh native listing;
  identical compressed chunks cannot hide a coforged physical-offset alias.
- Null datasets no longer block inspection/extraction of other vendor data. Null,
  scalar and zero-extent datasets stay distinct; bitfield class, compact layout,
  committed identity and null references survive supported edits/repacking.
- Selected compound fields can be written without reconstructing unrelated
  members. Independent rank2/scalar, points/hyperslab, reversed-field and vector
  cases verify protected siblings and fresh reopen behavior.
- Readiness, assessment and the MPI backlog describe the actual local-only scope.

Held-out independent native checks reject semantic mutations after both provider
hashes and common publication metadata are refreshed; restored positives pass.
Historical failures and the corrections remain recorded. Owner focused evidence
and independent targeted checks keep their exact source epochs; neither substitutes
for the full integrated run above.

The five acceptance questions have satisfactory answers within the recorded v1
boundary: no remaining ordinary advertised job was shown to require a new adaptor
implementation project; the reviewed variants compose through typed intent;
exclusions follow product/provenance/runtime boundaries; and source-current
independent checks support the repaired abstractions. Final acceptance also
requires current canonical native conformance, a clean installed package and
unchanged source/wheel release gates, recorded separately when actually passed.

## Reviewed exclusions and explicit limits

Direct ROS3/HDFS/S3 opens are excluded by the immutable captured-local-byte
provenance boundary: download then adopt. Arbitrary third-party native filter
plugins are excluded by the controlled-runtime boundary; unsupported received
filters produce admission faults. Python file objects, interactive completers,
raw handle passthrough and test/config helpers are language conveniences rather
than durable file workflows. Internal attribute compact/dense phase thresholds
are excluded as storage-form tuning; actual large-attribute/order outcomes are
implemented. Nested compound types are not a stable supported high-level h5py
workflow. None of these boundaries is a claim of arbitrary HDF5 ecosystem coverage.

Direct stored-chunk audit/copy covers the reviewed single-file gzip/shuffle/
Fletcher-32 layouts and unchanged compatible captured sources. Arbitrary external
precompressed injection is beyond this verified-value/file interface. Typed where
cannot combine with explicit selection or parallel extraction; variable-length
payloads cannot request the fixed-size streamed-memory budget. Bounds on objects,
elements, attributes, ranks and captured bytes remain visible in readiness and
the guide. Streaming byte controls include explicit native/cache headroom and
are not a universal claim about library or process RSS.

Some facts (UTF-8 attribute encoding, LZF/scale-offset presence, region references
and non-native fill values) are checked by fresh h5py readings because h5dump XML
does not express them faithfully. Null dataspaces are additionally confirmed from
h5dump DDL headers. Larger files use fresh streamed digests for preserved values
and selected-region independent readings within the declared verification model.

## Historical evidence

Earlier kit conformance at `0b29769` had 13 cases and 174 integrity probes; owner
r20 had 13 cases, 56 attack/control records and 43 lifecycle checks. Those receipts
are historical and do not qualify later direct-chunk, null or field-write repairs.
Root q25 at `de0df2f` passed 19 cases, 86 attack/control records and 142 lifecycle
checks before the final null/type/field repairs. Earlier metadata descriptions
of seven operations, all MPI unavailable, direct chunks/sieve tuning missing or
null/field writes already verified were superseded by actual reviewed repairs.
This review reconciles those claims without relabelling old execution as current.

## Final engineering acceptance

The master accepts the independently reviewed fixed-baseline scientific-file v1
scope after reconciling all 41 assigned inventory families, the reviewed
exclusions and the user-accepted local-MPI boundary. No required family remains
missing or unverified within that scope, and no known ordinary advertised
workflow requires a follow-up adaptor implementation project. This does not
claim arbitrary ecosystem, distributed MPI or future-release coverage.

Canonical native conformance at clean `c9daaa2` passed all 20 named cases,
270 integrity checks and both timeout/pre-launch cancellation checks. Its
receipt was explicitly recorded in `8b966d0`; source digest
`sha256:1a05c62b501f52cc4c03ce71ac4e085391ec3ef109573b5b187976302a668855`
remained unchanged after recording and checking the strict admission snapshot.
The broad integrated native suite, full host and Studio results above retain
their actual executed source identities.

A fresh isolated wheel built from clean `8b966d0` passed discovery, all four
programme providers' starters and bundled Help, native-free host discovery,
installed HDF5 creation/selected-field editing with exact uint64 siblings and
null dataspaces, fresh verification after removing the original producer file,
and a separate literal h5py consumer. Installed Zstandard round-trip and
source-removal verification and actual browser authoring also passed. All
packaged files were compared byte-for-byte with that source; every runtime
Python module was present. Wheel SHA256:
`87612e72717d9a060b839599085f7f6de79d3a3bd72dae49f14d873e29e021df`.

Unchanged source and wheel release gates passed with zero prohibited hits,
32 patterns including 26 private patterns, and the existing allowlist. The final
acceptance-note changes are outside the package, leave its bytes and source
digest unchanged, and have separate generated/admission/private-gate checks.
All native, canonical, host/Studio and installed evidence was retained with
individually revalidated hashes. Historical interrupted or failed runs remain
labelled accordingly. This is local engineering acceptance at the existing
package version; no push, publication, deployment or release is authorised.

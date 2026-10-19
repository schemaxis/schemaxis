# Output storage and retention review

Measured and checked against the working tree on 17 October 2026. This review
separates existing behaviour, the shared schema implementation, and proposals.
It does not authorise deleting or migrating any retained evidence.

## What is stored, and why

| Layer | Current location and ownership | Meaning and lifecycle |
| --- | --- | --- |
| In-process state | `adaptor_runtime.InputProgram`, `AdaptorSession`; `console_session._runtimes`; Studio job records and browser stores | Expanded visits, native clients, geometry and UI state. Native handles remain process-local. They are not a durable substitute for inputs or evidence. Losing a client invalidates its residency; it cannot simply be reconstructed from a Python object dump. |
| Studio recovery | A selected workspace's `session.json`, `session.lock`, `studio-settings.json`; optional scheduler files | Session envelope holds a checksum, active document UUID, monotonically increasing revisions, authored document and exact source text, diagnostics, undo/redo snapshots, configurations, attempts and checkpoint references. `_commit` serialises the whole state through atomic replacement and fsync. Recovery checks the envelope and marks interrupted running attempts; it does not resume native clients. |
| Reusable source | User JSON/YAML documents, adaptor `studio.json` and `studio/templates/`, workflow template bundles | Authoritative editable inputs. A workflow template is distinct from a saved parameter-value case; a template revision/digest binds that case to its workflow. Shipped starters are resources, not records of execution. |
| Saved case | Explicit filename chosen through `studio_cases` | Parameter values and template identity. Save detects external changes using the loaded digest; Save As chooses a new filename. This is not a clone of run evidence. |
| Run | User-selected output directory, or Studio `runs/case-<UUID-prefix>` | Retained `authored.json`, application-specific `plan.json`, `result.json`, `verification.json`, native worker/captured inputs, logs and outputs. Names are a mixture of explicit filenames, operation identity, UUID, ordered state/batch/attempt numbers; there is no universal timestamp-based case hierarchy. |
| Study/workflow | `state-00000/`, operation directories, `batch-0/attempt-0001/`, aggregate result/verification | Immutable attempt evidence, resolved inputs, handoff hashes, resource budgets and timing. Workflow reuse rechecks inputs and producer/adaptor evidence. Failed attempts remain evidence, not automatically disposable caches. |
| Shared schema | Output/workspace root `schemas/<hash>.json`, index and per-run `schema.snapshot.json` | The new framework capture records the authored contract. Objects belong to the root, not an arbitrary run. See [schema storage](../schema-storage.md) for exact identity, compatibility, integrity and portability. |
| Runtime snapshot | `runtime.zip` on application paths that use `artifacts.runtime_archive()` | A deterministic archive of core/adaptor code and resources plus notices and plugin metadata. It does not contain the native application's executable, system libraries or all external assets. It is a reproducibility dependency, not a schema. |
| Publications | Application-specific files and verification manifests; optional `named/` | Derived results with declared kind/hash/semantic checks. `output_naming.apply` first verifies the run, then hard-links within a filesystem or copies across filesystems and records `named/naming.json`. Logical duplicate names need not consume duplicate blocks. |
| Explicit native save | `console_session.save` destination and native save provenance | Copies a verified artifact from the current checkpoint; requires the appropriate preview/native-save capability. It is distinct from `write_source`, which preserves the authored source and its source format. |
| Backup/archive | Explicit storage-management destinations | Copies retained records and bundles shared schema dependencies. Byte/content verification proves archive completeness; it does not establish that an arbitrary relocated native run can be reused. See [storage management](../storage-management.md). |

The `evidence/` directory in the repository is a convention for bulky local
qualification outputs; it is git-ignored. `verification/` contains compact public
verification summaries. A user's ordinary output directory need not be named
`evidence`. Within a run, evidence includes authored/effective inputs, plans,
worker code, captured external inputs, native version/readback information,
stdout/stderr, integrity manifests, semantic checks and result artifacts. Each
adaptor defines its evidence membership; not every adaptor emits every filename.

Relevant implementation paths: [atomic storage](../../src/schemaxis/storage.py),
[session persistence/save](../../src/schemaxis/console_session.py),
[authoring history](../../src/schemaxis/authoring.py),
[case binding and execution](../../src/schemaxis/studio_cases.py),
[templates](../../src/schemaxis/workflow_templates.py),
[workflow coordinator](../../src/schemaxis/parallel.py),
[common studies](../../src/schemaxis/adaptor_runtime.py),
[runtime packaging](../../src/schemaxis/artifacts.py), and
[publication naming](../../src/schemaxis/output_naming.py).

## Representative lifecycle

```text
workspace/
  session.json                 # edits, source, revisions, undo/redo, checkpoints
  session.lock                 # live owner lock, not a deletion signal
  studio-settings.json
  scheduler.json               # only when using the execution scheduler
  inputs/report.json           # explicit authored save, path chosen by user
  cases/example.json           # optional saved template parameter values
  schemas/                     # root for sibling Studio preview checkpoints
  checkpoint-<uuid>/           # preview evidence, planning-only or native
  runs/
    schemas/index.json
    schemas/<content-sha256>.json
    case-<id>/
      authored.json
      schema.snapshot.json
      execution-plan.json
      result.json
      case.json
      analyse/batch-0/attempt-0001/
        authored.json
        schema.snapshot.json
        plan.json
        verification.json
        result.json
        ... application evidence and artifacts ...
      named/naming.json
      named/000001-analyse-table.csv
```

This is illustrative: the standalone case, study and legacy serial workflow
layouts differ. A schema is added after a successful native return or when a
workflow/study/checkpoint owner prepares its envelope; a native failure before
that boundary may retain evidence without a snapshot. Legacy readers still work
without one. `session.json` recovery is automatic on reopening the workspace;
explicit source saves are separate. There is no incremental session journal,
configurable archival tier, automatic source regeneration or storage cleanup
service today. The Case Runner's in-memory `records`/job list is not itself a
persistent browseable run catalogue, even though run files survive server restart.

Copying a complete shared root preserves relative schema references. Exporting a
single run must include its schema dependencies; raw copying only the run folder
may break those references. Some native/workflow receipts contain absolute paths
and refer to external inputs. Portable schema export does not rewrite those
receipts or promise native re-verification at arbitrary new paths. Restore at the
original location with dependencies intact, or separately qualify relocation.

## Measurements

Read-only scan of the retained 16 October final integration directory: **13,459
files, 91,705,123 logical bytes, 125,198,336 allocated bytes** from `stat` blocks.
There were **19,192,260 bytes (20.9%)** of exact repeated content across distinct
inodes. No hard-linked file duplication appeared in this sample. It includes a
stale wheel build tree, qualification variants and private native profiles, so it
is a qualification-workspace sample, not an estimate of a typical user's case.
Filesystem compression/reflink sharing was not measured. Content equality alone
is not evidence that files can safely be omitted or deleted.

The repeated Calc/LibreOffice private profiles are prominent: 40 identical
75,798-byte database files, 40 identical 46,601-byte companion files, and 40
35,313-byte configuration files. These profiles also provide native isolation;
sharing their writable directories would sacrifice that property. Captured
Cantera mechanisms repeat 72 times at 10,033 bytes each, but must remain available
with their exact identity for reproducibility.

Compression below uses three in-memory round trips and median wall time. Input
bytes came from retained/generated files; all decompressions were compared with
the original bytes. These timings omit filesystem write/fsync, cold-cache and
network costs, and were collected while other host work was active. They are
representative observations, not service-level guarantees.

| Sample | Original bytes | gzip-6 bytes / encode / decode | gzip-9 bytes / encode | xz-6 bytes / encode / decode |
| --- | ---: | --- | --- | --- |
| ParaView authored schema | 4,077,402 | 118,479 / 19.00 ms / 2.40 ms | 113,067 / 36.96 ms | 71,848 / 249.44 ms / 4.23 ms |
| Workflow authored schema | 6,497,815 | 196,214 / 30.75 ms / 3.84 ms | 184,267 / 60.06 ms | 101,708 / 386.39 ms / 6.14 ms |
| PrusaSlicer plan | 9,204 | 2,262 / 0.12 ms / 0.03 ms | 2,246 / 0.16 ms | 2,268 / 2.50 ms / 0.13 ms |
| R authored input | 2,140 | 303 / 0.02 ms / 0.01 ms | 299 / 0.03 ms | 332 / 0.87 ms / 0.02 ms |
| PrusaSlicer verification | 8,998 | 2,619 / 0.13 ms / 0.03 ms | 2,617 / 0.15 ms | 2,552 / 1.75 ms / 0.14 ms |

Schema sharing measurements are in the [schema implementation review](../../verification/2026-10-17-schema-storage.md).
Sharing ten captures saves approximately 88–90% including reference/index
metadata, without requiring compression or changing old exact-byte snapshots.

One newly generated runtime archive contained **7,180,429 bytes**, built in
**0.721 s**. Its compressed Studio Help members accounted for 3,327,357 bytes and
adaptor guidance for 1,839,565 bytes, versus 1,760,523 bytes for other file members
(plus ZIP overhead). The archive's uncompressed payload was about 51.7 MB. This
supports investigating runtime packaging and exact archive reuse, but is not a
measurement of savings already implemented. No retained `runtime.zip` files were
present in this particular integration sample; earlier audit claims are not
substituted for a current duplication count.

## Prioritised options

| Priority and recommendation | Benefit | Cost / stopping point | Compatibility and effort | Verification |
| --- | --- | --- | --- | --- |
| P0: shared immutable schemas (implemented separately) | ~88–90% saving for ten identical captures; explicit historical contract | Schema generation and hash verification still cost CPU; avoid treating index counts as complete references | Old v1 retained; new v2 refs; moderate bounded change | All-route coverage, two-adaptor reuse, changed content, concurrency, failure and portable export |
| P1: compress cold case archives (safe tool available) | Large text compression and fewer filesystem blocks; native independence while archived | Requires extraction for ordinary readers; already-compressed media/ZIPs may save little. Sources retained until safe removal exists | Archive wrapper, no evidence format replacement; moderate | Full file membership/hash/mode checks; tamper, stale plan, restore and collision tests |
| P1: content-address exact runtime archives (proposal) | Up to one 7.18 MB archive per distinct runtime instead of per execution; also avoid repeated creation | Must hash actual source, plugin packages/resources and notices; mutable checkout invalidation is essential | Requires reference-aware native launch/export and legacy ZIP fallback; medium/high | Native launch from retained bundle, changed plugin/source invalidation, offline export, concurrent publication and failure tests |
| P1: omit host Help/guidance from native-only archive after dependency audit (proposal) | This sample has ~5.17 MB compressed in those two categories | Do not omit declarations/native resources used by actual workers; two archive flavours add maintenance | Preserve notices; audit plugin imports and resource reads; medium | Every qualified native route and plugin runs with minimal bundle, source provenance remains complete |
| P2: gzip-6 large JSON as an explicit storage format (proposal) | ~97% schema compression even after content deduplication | gzip-9 saves only 5.4 KB on the 4 MB schema for ~18 ms extra encoding; xz adds ~230 ms for another 46.6 KB. Prefer gzip for frequent writes; xz only for cold tiers if measurements justify it | New readers/manifest encoding tags, migration/export support required; medium | Raw canonical identity independent of compression; size bounds, decompression corruption/bomb tests, cold/hot read measurements |
| P2: snapshot/journal history with periodic compact checkpoints (proposal) | Avoid repeated full document/source/undo copies in every `session.json` write | Recovery and undo correctness become more complex; smaller storage is not worth unrecoverable state | Versioned session format and tested migration; high | Crash at every journal/checkpoint publication, invalid source roundtrip, undo/redo, external save conflicts; benchmark real large sessions |
| P2: lazy load retained schemas, plans and Help by identity (proposal) | Less startup/RSS and unnecessary parsing; does not itself remove on-disk evidence | Cache invalidation must account for plugins, contract versions and updates | Keep existing full-read APIs; medium | Same search/schema/planning results; cold/warm timings and memory on real documents |
| P3: regenerate selected derived artifacts instead of retaining them (proposal only) | Potentially large meshes/images/results savings | Native rerun may be slow, nondeterministic or unavailable; never infer feasibility from adaptor name/version | Needs per-artifact reconstruction contract and dependency inventory; high | Remove only fixture copies, recreate under pinned environment, compare semantic results/digests and time reconstruction |

Before regeneration can be considered safe, retain authoritative authored and
resolved inputs, captured external files and hashes, units/CRS/timebase, random
seeds where relevant, exact Schemaxis/plugin code and schema settings, native
binaries/version/build and licences, mechanisms/fonts/colour profiles/materials,
system libraries and environment/resource policy. Establish deterministic output
or an accepted semantic tolerance and confirm those dependencies are available.
An input document plus an application version is insufficient. Independent
verification evidence and provenance should survive even if an explicitly
regenerable large artifact is later omitted. No current generic regeneration
contract establishes these conditions across the adaptor library.

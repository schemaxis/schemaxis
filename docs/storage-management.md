# Storage inspection and portable case preservation

For packaged application runtimes and saved downloads, use the separate
[application module cache](application-modules.md#cache-inspection-and-cleanup).
Its explicit ownership and execution leases allow reviewed removal of managed
runtime references. The preservation commands below retain user case data.

`schemaxis storage` inspects an explicitly selected output root, plans preservation
of explicitly selected cases, creates verified backups/ZIP archives, and restores
those bundles. Every case needs retained `authored.json`. Source cases,
installations and shared schema stores are retained by every operation.

```sh
schemaxis storage --help
schemaxis storage inspect --root OUTPUT_ROOT
schemaxis storage inspect --root OUTPUT_ROOT --no-installations
schemaxis storage plan --action compress --root OUTPUT_ROOT --run run-a \
  --run run-b --older-than-days 30 --destination ARCHIVES/cases.zip --save review.json
# Review review.json, including sources, hashes, dependency effects and confirmation.
schemaxis storage apply review.json --confirm CONFIRMATION_FROM_REVIEW
```

Paths supplied with `--run` are relative to the selected root. There is no implicit
“all”, glob or unused-data selection. Duplicate/overlapping selections, paths
outside the root, shared-schema directories, links, special files and existing
destinations are rejected. The minimum age considers the newest file or directory
modification in each case; it is a selection rule, not evidence of last use.
`--save` exclusively creates the requested plan file; without it, planning only
prints JSON and creates no destination.

The confirmation digest binds the complete plan, selected file hashes and schema
dependencies. Apply recomputes it and the plan, refusing changed sources or changed
schema dependencies. Known held console/agent/scheduler owner locks under the
selected root block preservation. File checks are repeated after copying. These
checks cannot establish universal inactivity across native writers, processes
without framework locks, or workspaces above a narrowly selected root. They are
sufficient for the implemented non-destructive preservation scope; they do not
authorise automated source removal.

Known owners include the workflow/study `.coordinator.lock` as well as console,
agent and scheduler ownership. A narrowly selected root cannot inspect an owner
outside that boundary; choose the actual containing workspace when applicable.

Three preservation actions are available:

| Action | Destination | Behaviour |
| --- | --- | --- |
| `backup` | New directory | Portable case copies with checksummed membership manifest. |
| `archive` | New ZIP file | Same bundle with ZIP stored members, without compression. |
| `compress` | New ZIP file | Same bundle with ZIP deflate compression, level 6. |

Each bundle has this layout:

```text
storage-manifest.json
 data/
   run-a/
     authored.json
     evidence/input.snapshot.json
     schemas/…
     …retained run files…
   run-b/…
```

The [shared schema export](schema-guide.md) copies every nested schema dependency
into each exported case's local store. Original content, logs, publications and
provenance are retained; snapshot references are republished for their new schema
store, and copied shared publication manifests retain their original directory as
a location hint for verifying the selected copy. Native receipts are not rewritten.
The manifest records exact file membership, SHA-256 identities, byte counts,
ordinary file permissions and empty directories. Source originals remain
unchanged. Checksums establish integrity, not authorship or trust in an archive.
Directory backups are verified after publication; archives are independently
stream-read and checked before publication. Interrupted directory publication
leaves `.storage-incomplete`; that backup is refused as a restoration source.

Plans report zero source-deletion bytes and zero immediate net savings because the
source is retained. Compressed size is unknown until measured. Apply reports
`storedBytes`, `contentBytes`, `compressionSavingsBytes` (which can be negative for
small files), and `netAdditionalStorageBytes`. These are logical file sizes, not
filesystem allocated blocks or sparse-file savings. Existing compressed images,
video and runtime ZIP files may compress little. Portable dependencies can add
bytes that were previously shared outside a selected case.

Restore a ZIP archive or directory backup through another reviewed plan:

```sh
schemaxis storage plan --action restore --archive ARCHIVES/cases.zip \
  --destination RESTORED --save restore-review.json
schemaxis storage apply restore-review.json --confirm CONFIRMATION_FROM_REVIEW
# Restored run-a is under RESTORED/data/run-a.
```

Restoration rejects traversal paths, duplicate names, links, omitted/unexpected
members, changed hashes, changed backups and existing destinations. It streams
regular files explicitly instead of calling ZIP extract-all. `--max-bytes` bounds
the total declared uncompressed content (default 8 GiB); raise it deliberately for
larger bundles. Directory backups and archives obey the same bound. Restore keeps
the backup/archive and creates a new copy; it does not overwrite an existing case.

Schema portability and application portability are separate. Absolute artifact,
attempt or external-input paths in retained receipts/documents are not rewritten.
A relocated bundle is inspectable evidence with resolvable schemas; arbitrary
application verification or native reruns at a new root are **not** established.
Native reuse can require original paths, inputs, plugins, application binaries,
versions and resources. Preserve those independently and qualify the actual
restored workload before relying on it. Archive integrity alone is not native
workflow qualification.

Verification establishes current process-level integrity. Crash durability,
filesystem snapshots, access-control lists, extended attributes and ownership
preservation are not qualified. Sources remain available if publication fails.

## Application inventory and derived data

Inspection uses the existing private configuration's selected application paths.
A configured executable's size is `measuredPathBytes`; it is not the size of its
whole installation. A configured directory is measured recursively over regular
files, excluding symlink targets. `installationBytes`, dependency closure,
`lastUsedAt` and `recordedUseCount` remain null where no ledger exists. Declared
runtime/executable metadata is shown separately from measured installations.
Unknown usage never means unused. Use `--no-installations` to omit private paths.

Schemaxis currently records application locations, not installation ownership,
package-manager receipts or usage history. Managed uninstallation is unavailable;
use the application's distributor/package manager with an explicitly selected
installation. Inspection marks ownership external or unknown and never guesses an
installation root from an executable's parent directory.

No derived-file deletion is offered: retained input/version alone cannot establish
reproducibility without available external inputs, plugins, binaries, settings and
verified deterministic regeneration. `derivedRemovalCandidates` is empty and
`regeneration` remains `not established`. Shared schema inspection reports verified
references, objects, faults and protected store paths. No schema garbage collection
or reference-count-based deletion is implemented.

## Opt-in interval policies

A saved policy records named runs, a minimum age and an interval. It generates
reviewable preservation plans when invoked; it installs no scheduler, worker,
background process or deletion timer:

```sh
schemaxis storage policy create monthly.json --name monthly \
  --root OUTPUT_ROOT --run run-a --run run-b --destination ARCHIVES \
  --action compress --every-days 30 --first-due 2026-11-01T00:00:00Z \
  --older-than-days 30
schemaxis storage policy due monthly.json
```

`due` returns the current interval's plan and skipped young cases; before the first
due time it returns no plan. It changes neither policy nor cases. Copy the returned
`plan` object into a JSON file for explicit `storage apply`. `--now` accepts an ISO
8601 instant with an offset for deterministic previews. Each interval uses a new
named destination; an already existing destination requires review and is never
overwritten. Repeated previews do not mean multiple background jobs are running.
The existing execution scheduler accepts declared application workflows; arbitrary
filesystem deletion is not introduced through that contract.

Unattended cleanup, managed uninstall, source-removing archival and regeneration
pruning remain unimplemented. Safe implementation needs durable installation
ownership/dependency/usage records and a reliable active-run lifecycle shared by
all launch routes, plus a retention policy and restoration/requalification checks.
The present commands report this scope explicitly and provide verified
non-destructive preservation. They do not claim completion of those broader Task E
requirements. See the [verification record](../verification/2026-10-17-core-usability.md).

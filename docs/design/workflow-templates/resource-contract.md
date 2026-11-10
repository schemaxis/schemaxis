# Captured resource foundation

Implemented host API in `schemaxis.workflow_resources`:

```python
capture(source, destination, *, kind='file', members=None,
        max_files=10000, max_bytes=1073741824) -> manifest
verify(destination, *, max_files=10000, max_bytes=1073741824) -> manifest
```

`file` captures one regular file using its basename. `file-set` captures an
explicit nonempty list of unique relative file paths beneath a source directory.
`directory` captures the complete regular-file tree, including empty directories.
The last two accept a directory as `source`; only `file-set` accepts `members`.

The destination must not exist and must be outside the source. A snapshot contains
`resource.json` and `data/`. The canonical `schemaxis.resource/1` manifest records
kind, completion, sorted file paths, sizes and SHA-256 hashes, sorted directories,
total bytes and a semantic manifest digest. It contains no workstation source
paths. Verification needs only the snapshot and checks its exact contents.

Capture copies bytes without changing input permissions. It checks input identity,
size and modification/change metadata around reads, rehashes copied bytes and
compares the final source inventory. Ordinary source changes abort publication;
the retained partial destination cannot be reused. The completion manifest is
published only after these checks. An uncertain manifest durability error causes
removal of the completion marker; if removal also fails, the structured fault
explicitly reports uncertain publication.

Constituent files and their directories are synchronised before manifest
publication, including newly created destination ancestors. A directory
synchronisation failure leaves the retained data without a completion marker.

Both operations enforce the caller's file and byte limits. The file limit also
independently bounds subdirectories, so empty directories cannot bypass bounds.
Manifest JSON is limited to 16 MiB and relative paths to 4096 characters. Links,
symlink ancestors, special files, duplicate members, absolute member paths,
backslashes and path traversal are rejected. No native process is started.
Source and destination filesystem paths also reject every `..` component before
normalisation, so a missing ancestor cannot silently select a different path.

Faults distinguish invalid or unsupported resources, resource limits, changed
inputs, mismatched captured evidence, I/O failure and existing output. Source
deletion or filesystem errors can report an I/O fault; they never certify a
complete capture. The API uses Schemaxis's existing structured fault envelope.

This foundation does not resolve dependencies inside native project files, infer
formats, coordinate live writers, acquire application leases, enforce read-only
OS permissions or integrate resources into template bindings yet.
Writers must expose a stable checkpoint. Checks are not a sandbox against an
adversary concurrently replacing filesystem ancestors. Hashes detect accidental
changes; a consumer requiring provenance must pin the trusted manifest digest
separately, since a rewritten manifest is not an independent attestation.

## Workflow consumption (first slice)

`schemaxis.captured_inputs` and `schemaxis input adopt|verify` reuse this format
unchanged. `adopt` returns a `$resource` reference holding the absolute snapshot
directory, the trusted manifest digest, an optional `member` (required for
directory/file-set consumers), optional `origin`, and optional `maxFiles` and
`maxBytes`. Non-default adoption bounds are written into the reference, so later
checks use the same limits; they are never enlarged automatically. The reference
is validated structurally in `workflow.validate`.
Workflow planning, serial and scheduled dispatch, resume comparison and whole-run
verification each call `verify`, compare the pinned digest, refuse a mismatch with
`INPUT_CHANGED` and substitute `data/<member>`. Serial and scheduled execution
check the same pinned snapshot again after each consumer returns and before its
success is recorded, so an ordinary edit during execution fails the run with
`verified: false`. This detects concurrent modification; it does not defend
against an adversary replacing and restoring bytes between checks. The digest is
never recomputed into a new trust root. The consuming route's `acceptResource(document, pointer, resource)`
hook decides whether that option may read the kind and member. A route without a
hook refuses. Evidence enters the run's `handoffs` with units and frame `unknown`.

The ParaView pilot permits single-file readers, closed XML-piece readers (every
`Source`/`file` reference must be a captured member of a directory or file-set
snapshot, with header-checked VTK XML types matching their names) and the
OpenFOAM reader with a whole case directory whose reader-openable files (a
conservative superset of the ParaView 5.13.3 reader's case layout, within bounded
scan sizes) contain no active `#` directive, overlong string or binary data, and
whose selected marker does not begin with `controlDict`. Resume stays
conservative: ParaView `reusableInputs` still declines file readers, so resumed
consumers rerun after the snapshot is rechecked. Workflow and workflow-design
JSON Schemas admit the closed `$resource` shape (`captured_inputs.reference_schema`)
only at reader positions declared by the route's `capturedInputSchema` hook, which
uses the same reader sets as `acceptResource`. Standalone authored schemas do not.
Studio's nested operation editor requests the workflow-scoped schema
(`/api/schema?scope=workflow`); nested validation rechecks snapshots and marks the
draft `requiresWorkflow` without calling it deferred. Schema acceptance is
structural; snapshot bytes, membership and reader policy are checked by the host.
Existing `$document` composition is supported: after `workflow_inputs` resolves
references, `captured_inputs.consumed` excludes only top-level parser-owned
metadata (`settings`, `definitions`, `dimensions`), so consume, post-consumer
recheck and Studio `requiresWorkflow` all act on the same resolved reader fields.
Authored metadata is retained unchanged; operation-level reference shape checks
still apply.
Adoption remains CLI/API only. Not yet implemented: standalone consumption,
template parameter binding, a Studio adoption/editing action, selective
continuation after a human edit, native-application handback of an edited
snapshot, OpenFOAM case-dependency enumeration, and policies for other adaptors.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests/unit
-p test_workflow_resources.py -q` exercises 30 cases, including mid-read source
mutation, directory membership changes, incomplete publication, content tampering,
missing/unexpected members, path escape, links, special files, bounds, source
preservation, portable verification and exclusive destination ownership.

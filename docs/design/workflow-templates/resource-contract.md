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
OS permissions or integrate resources into template bindings/execution yet.
Writers must expose a stable checkpoint. Checks are not a sandbox against an
adversary concurrently replacing filesystem ancestors. Hashes detect accidental
changes; a consumer requiring provenance must pin the trusted manifest digest
separately, since a rewritten manifest is not an independent attestation.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests/unit
-p test_workflow_resources.py -q` exercises 30 cases, including mid-read source
mutation, directory membership changes, incomplete publication, content tampering,
missing/unexpected members, path escape, links, special files, bounds, source
preservation, portable verification and exclusive destination ownership.

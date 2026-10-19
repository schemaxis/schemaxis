# Shared schema storage

Schemaxis retains a run's authored document contract as a small reference to a
workspace-owned schema object. Sibling runs with identical schemas share that
object. The object belongs to the output root, so removing one run does not remove
a dependency owned by another run.

## What existed before this change

[`schema_snapshots.py`](../src/schemaxis/schema_snapshots.py) already provided an
application-independent, **explicit** capture command. It stored exact input bytes
at `schemas/<sha256>.json`, with immutable `*.snapshot.json` manifests next to the
`schemas` directory. Its identity was the SHA-256 of the original bytes, including
whitespace. It supported every exported document schema, not just ParaView.
It did not automatically capture schemas for executed runs, share between separate
run directories, or maintain a provenance index.

[`adaptors/paraview/schema_bundle.py`](../src/schemaxis/adaptors/paraview/schema_bundle.py)
is a separate optional category export: common definitions, readers, filters,
rendering, writers, and an entry point. It uses relative JSON Schema references
and its own hash manifest. All six members must travel together. Grouping makes
category schemas accessible; it does not eliminate repeated complete run copies.
That format and the existing standalone schema export commands are preserved.

Schemas are generated from registered host-side declarations and schema bindings
by [`schema.export_schema`](../src/schemaxis/schema.py) and
[`schema_authoring`](../src/schemaxis/schema_authoring.py). Native applications are
not imported to generate, retain, inspect, or read these schemas. Checked-in
`docs/generated/*.schema.json` files remain generated reference documentation;
they are not the authoritative schema store for executed runs.

## Sharing boundary and layout

A standalone run uses its output directory's parent as the shared output root.
A nested workflow or common adaptor study uses the parent of its outermost
recognised workflow/study output. Recognition requires an authored workflow
version or the common study receipt protocol, rather than an arbitrary ancestor
file called `authored.json`. The Python API also accepts an explicit
`workspace_root`, which must be an ancestor of the run.

```text
outputs/
├── schemas/
│   ├── .lock
│   ├── index.json
│   ├── <calc-schema-sha256>.json
│   └── <ffmpeg-schema-sha256>.json
├── calc-case-A/
│   ├── authored.json
│   ├── schema.snapshot.json        # root: ".."
│   ├── plan.json
│   └── verification.json
├── calc-case-B/
│   ├── authored.json
│   └── schema.snapshot.json        # same Calc object
└── workflow-run/
    ├── authored.json
    ├── schema.snapshot.json        # workflow envelope
    └── operation-A/
        ├── authored.json
        └── schema.snapshot.json    # root: "../.."
```

The framework integration is in the common execution and verification boundaries
([`adaptor_runtime.py`](../src/schemaxis/adaptor_runtime.py),
[`workflow.py`](../src/schemaxis/workflow.py), and
[`parallel.py`](../src/schemaxis/parallel.py)). The registry and bound direct
adaptor verifiers check retained dependencies. Studio cases and ordinary previews
use these execution paths. Studio live native checkpoints have an explicit capture
at their checkpoint boundary. Opening/editing a Studio document and exporting a
schema for an editor do not create run evidence.

Native adaptors that require a fresh output directory still create it themselves;
the common boundary captures their contract after native return and before native
verification. A native process that fails before returning may leave an incomplete
run without a snapshot. The outer workflow/study captures its contract after
claiming its output directory. Resume verifies a retained snapshot rather than
silently replacing it with today's declarations.

## Identity and provenance

New shared references use `schemaxis.schema-snapshot/2`. Content identity is SHA-256
of finite UTF-8 JSON with sorted object keys, compact separators, and one trailing
newline (`python-json-sort-keys-utf8/1`). Duplicate keys and non-finite numbers are
rejected. Whitespace and object-key order do not split identities; changed
constraints, annotations, strings, array order, and represented numeric types do.
For example, `1` and `1.0` remain distinct. This is a deliberately conservative
canonical representation, not a claim of semantic equivalence or RFC 8785 support.

A reference records the provider, literal document version, authored/expanded
flavour, relative root, content path, hash, byte count, canonicalisation, and
provenance. `schemas/index.json` maps hashes to byte counts and distinct provenance
observations. Provenance is separate from identity, so different observations of
the same content still share one object. Observations include:

- The adaptor source, package when declared, and route schema binding.
- The schema generator's installed package version, or `null` if unavailable.
- The declared application runtime family, and `actualVersion: null` when the
  capture has no native version measurement.
- Explicitly supplied schema-generation settings; ordinary case parameters are
  not assumed to change a schema.

A document version is an input contract version, not an application version.
Provenance does not assert that these fields alone can regenerate an old schema:
plugin/declaration code and any additional generation inputs would also be needed.
The retained bytes are the reproducibility record. Hashes establish content
integrity, not authorship or authenticity.

## Reading, failures and concurrent writers

`schema_snapshots.read(path)` accepts both original v1 manifests and new shared v2
references. It verifies byte count, hash, and the exact document version without
regenerating the schema. Shared reads also validate canonical encoding, ancestor
root syntax, and path ownership. Shared schemas must be standalone: external
schema references are rejected instead of silently omitting their dependencies.
Literal `$ref` keys inside annotation/default/constant data remain literal data.
Use the separate explicit bundle format for multi-file schemas.

Missing objects, altered bytes, malformed references, wrong input/schema versions,
and symlink paths fail with `INVALID_SCHEMA_SNAPSHOT`; a conflicting immutable
capture fails with `SCHEMA_SNAPSHOT_EXISTS`. New shared writes translate filesystem
failures into `SCHEMA_STORAGE_ERROR`. There is no automatic regeneration or
replacement of corrupted retained evidence. Restore the original dependency from
a verified backup, or create a new run with a newly captured contract.

Writers use a POSIX advisory lock for each `schemas` directory, complete temporary
files, file/directory `fsync`, atomic object linking, and atomic index replacement.
Concurrent processes cannot lose each other's provenance updates. Lock acquisition
is bounded to ten seconds (`SCHEMA_STORAGE_BUSY`); process termination releases the
lock. The supported platform is a local POSIX filesystem providing these semantics.
Network/object filesystems and adversarial concurrent directory replacement have
not been qualified.

An interruption can leave a complete unreferenced object or an index observation
without a run reference. Neither is treated as permission to delete. Reads do not
depend on the index. A corrupt or missing index with existing objects blocks new
shared captures until explicit repair:

```python
from schemaxis.schema_snapshots import inspect, rebuild_index

report = inspect("outputs")       # read-only; includes faults and protected paths
index = rebuild_index("outputs") # explicit metadata repair, not data migration
```

Repair verifies objects and references before atomically rebuilding metadata. It
refuses missing/corrupt dependencies or uninspected symlink subtrees. Complete
objects with no surviving reference retain an empty provenance list, meaning
unknown provenance. Unknown provenance and usage are never labelled “unused”.

## Copying, exporting and cleanup

Copying or moving the **entire output root**, including `schemas/`, preserves all
relative references. Copying only a run directory does not automatically bring its
parent store and is insufficient. Create a portable run export instead:

```python
from schemaxis.schema_snapshots import export_run, read

summary = export_run("outputs/workflow-run", "exports/workflow-run")
schema_bytes = read("exports/workflow-run/schema.snapshot.json")
```

The export copies the selected run, resolves every nested snapshot, and publishes
its dependencies inside the destination's `schemas/` directory. New references
are rebased to that destination; old v1 captures retain their exact bytes and
adjacent `schemas/` layout. Legacy imported captures with unresolved external
schema references remain readable but cannot be certified as portable exports.
Existing destinations and symlinks are refused. All
exported references are rechecked. A failed copy leaves
`.schema-export-incomplete` and never deletes or modifies the source. Portable
schema dependency resolution does **not** prove that native artifacts with embedded
absolute paths can relocate, or that external user inputs have been included.
Application-specific verification and retention requirements still apply.

When a run has shared `publication-metadata.json` companions, export adds a
`recordedDirectory` location hint to each copied manifest. Shared publication and
workflow verification resolve recorded absolute paths inside that run's selected
copy, including nested jobs and studies. Native receipts, authored inputs, handoff
identities and their hashes stay unchanged. Moving or re-exporting the copy retains
the first producing location; verification never falls back to files at that old
location. Escaping paths and linked components are refused. Run-relative names also
work; legacy paths relative to the original process's working directory need an
adaptor update before they can be portable.
Export or back up before moving an original run: moving it by hand without an
origin hint can invalidate its recorded paths, and exporting after that move
cannot recover the missing original location.

The location hint is not proof of correctness. Each adaptor still has to verify
the retained native artifacts and any captured source independently. Scheduled
runs can verify without original inputs only when their adaptor supplies complete
verified capture bindings through `retainedInputs` (see [adaptor hooks](adaptors.md)).
Fresh execution and reuse continue to check current source bytes. Adaptors without
that hook retain their original-input verification requirement; embedded native
absolute paths and application-specific replay bindings are not rewritten by export.

Run removal must leave the root's `schemas/` store intact. `inspect()` reports
verified local references, corruption/missing-reference faults, and protected store
paths. It deliberately returns `usageComplete: false`: copied/external references
or active writers cannot be ruled out by a bounded scan. The index is descriptive
metadata, not a reference count. There is no automatic schema garbage collection;
storage tooling protects shared stores. Explicit export/archive verification is
required before any separately authorised source removal.

## Coverage and limits

The initial acceptance check captures all 22 registered routes across the 20
existing application adaptors, plus the workflow envelope:

| Adaptor | Captured document routes |
| --- | --- |
| ParaView | `schemaxis/1` |
| Blender | `schemaxis.blender/1`, `schemaxis.blender.render/1` |
| FreeCAD | `schemaxis.freecad/1`, `schemaxis.freecad.assembly/1` |
| Aseprite, Calc, CalculiX, Cantera, FFmpeg | Each adaptor's primary `/1` route |
| Gmsh, Godot, ImageJ, Inkscape, KiCad | Each adaptor's primary `/1` route |
| ngspice, Octave, Premiere, PrusaSlicer, QGIS, R, Shotcut | Each adaptor's primary `/1` route |
| Workflow | `schemaxis.workflow/1` envelope, with registered operation schemas |

The test enumerates the registry rather than freezing this application list, so
new or plugin routes with schemas use the same framework capability. No adaptor
must manufacture a schema for a route that is not a versioned execution document.
Legacy dynamic console providers that expose planning without a schema binding
also return no snapshot; errors in a declared schema binding still propagate.
Legacy unversioned inputs return no snapshot; older runs without one remain
readable. Studio workflow-design/template/value documents are authoring records,
not additional application run routes. The synthetic `fixture_geo` integration is
a test fixture and is not an installed application.

See [the measured verification record](../verification/2026-10-17-schema-storage.md)
for repeated storage savings, host tests, failure coverage, and remaining limits.

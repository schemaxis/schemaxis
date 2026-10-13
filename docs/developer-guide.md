# Developer guide

Use the [authoritative completion checklist](adaptor-completion.md) for new adaptors
and changes to existing operations, fields and routes.

The host layer is dependency-free Python3.10+. Native adaptors run in their own
application interpreters. `DefinitionGraph` validates dependencies;
`RuntimeClosure` owns active objects, applies changes and invalidates downstream
nodes. Discovery/planning must not import native modules.

## Adding a ParaView filter or reader

1. Inspect the public API in the supported ParaView runtime. Record constructor,
   input ports, property paths, enums and type/association constraints.
2. Add a `NativeFilter` subclass with a `declaration` dictionary in a catalogue
   module and register it in that module's `FILTER_CLASSES`. See `more_filters.py`.
3. Declare options with typed bounds/defaults, named input ports and trusted native
   property paths. Reader filenames are constructor options. Author documents may
   only select registered operations; arbitrary reflection and Python are excluded.
4. Add cross-property validation where simple value schemas are insufficient.
5. Add host rejection tests and a native example with independent expected results.
   Exercise both execution and durable artifact reopening.

This dictionary mechanism is the general in-repository filter/reader adaptor. It
is not a user-supplied arbitrary proxy or plugin loader. Runtime archives include
Schemaxis's packaged source; dynamic host-only registration will not automatically
appear in the native child interpreter.

## Writers

`schemaxis.native.geometry` selects a verified XML writer/reader pair by dataset type.
To add a writer, specify output type and losses, implement publication planning and
membership, write it, reopen it independently, and compare meaningful content.
Update receipts and tamper tests. An extension ending in the right suffix is not
proof of a successful export. Generic arbitrary `SaveData` options are not exposed.

## Blender

`blender_adaptor.py` plans and verifies; `blender_native.py` creates, updates,
observes and reopens; `blender_operations.py` declares curated geometry;
`blender_meshes.py` implements native mesh creation; `blender_settings.py` defines
render controls without importing Blender. Reuse logical object identities when
parameters change, and evaluate upstream modifiers before copying geometry.

## Checks

Run the host suite from the quick reference. Native acceptance examples include
`source-coverage.json`, `extended-coverage.json`, `blender-gallery.json` and
`blender-showcase.json`. Run `check_gallery.py RUN` and `check_blender.py RUN` for
independent geometry checks. The reader fixture script is run with `pvbatch` and
creates a runnable reader job. Keep bulk evidence in ignored `evidence/`; record a
compact dated summary in `verification/`.

Rectilinear snapshots hash only each axis's dimension-sized coordinate prefix:
ParaView5.13.3 Fetch can pad these arrays to total point count with undefined values.
All active coordinates are still checked; too-short and nonfinite active arrays fail.

Do not claim MPI qualification, arbitrary option combinations or full application
coverage from the serial acceptance examples. Keep discovery, docs and tests aligned.

## Schema and reference export

Use [the schema framework](schema-guide.md) to export existing declarations or a
new typed settings dictionary. `schemaxis schema` runs without native apps. Regenerate
with `PYTHONPATH=src python3 tools/export_input_reference.py`; use `--check` to
detect documentation drift. The input reference distinguishes schema structure
from the semantic and native checks that still require `plan`/`run`.

The current implementations live in `src/schemaxis/adaptors/paraview` and
`src/schemaxis/adaptors/blender`; the top-level modules named above are compatibility
imports. See the generated module index and human-input guide for the newer
spatial authoring layer.

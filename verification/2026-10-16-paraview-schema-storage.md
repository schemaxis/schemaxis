# ParaView schema grouping and retained storage — 2026-10-16

Added optional host-only tools for portable schema captures and a ParaView schema
bundle. Existing standalone exports, Studio schemas and capability pointers keep
their existing contracts. This is schema-tooling verification, not native
qualification; adaptor readiness and native qualification records were not changed.

## Commands and observed results

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_schema_snapshots.py -q
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_paraview_schema_bundle.py -v
```

Seven snapshot tests passed. Four bundle tests passed together, including offline
full-document/example parity and exact reconstruction of both schema flavours.
The subsequently added malformed-reference test passed separately; the expanded
literal-reference test, covering a pointer into a shared definition, also passed
again. These exercise five final bundle tests. The installed optional `jsonschema`
validator used its offline `RefResolver`; tests also support newer
`referencing.Registry` installations. Network retrieval is blocked by the test
resolver. Native applications were neither imported nor launched.

CLI smoke checks used fresh temporary directories:

```bash
PYTHONPATH=src python3 -m schemaxis.schema_snapshots capture evidence/schema-store \
  --name before --input docs/generated/paraview.authored.schema.json --version schemaxis/1
PYTHONPATH=src python3 -m schemaxis.schema_snapshots read \
  evidence/schema-store/before.snapshot.json > retained-paraview.schema.json
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.schema_bundle evidence/paraview-bundle
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.schema_bundle evidence/paraview-bundle --check
```

The retained schema round trip reproduced the input bytes exactly. Bundle checking
reported `verified: true`, six schema members and entry point
`paraview.schema.json`. The paths above are reusable examples of those commands;
the temporary smoke-check outputs were not retained as release evidence.

## Measured sizes

Ten fresh captures of the same current ParaView authored document schema shared
one schema object. Counts below include the ten snapshot manifests:

| Storage | Bytes |
| --- | ---: |
| One compact authored standalone schema | 4,077,402 |
| Ten independent copies | 40,774,020 |
| One shared object plus ten manifests | 4,080,622 |
| Bytes avoided across ten captures | 36,693,398 |

The shared store reduced this repeated-capture footprint by 90.0%. Measurements
used actual exported schema bytes and filesystem file sizes, with native-import
blocking enabled.

| Bundle member | Authored bytes | Expanded bytes |
| --- | ---: | ---: |
| Common | 134,448 | 18,097 |
| Readers | 1,093,720 | 563,491 |
| Filters and source generators | 2,734,073 | 870,466 |
| Rendering | 15,397 | 10,803 |
| Writers | 211,908 | 129,178 |
| Full-document entry point | 42,181 | 40,564 |
| All schema members | 4,231,727 | 1,632,599 |
| Equivalent compact standalone schema | 4,077,402 | 1,534,063 |

Bundle totals exclude the small hash manifest. Grouping adds 3.8% authored and
6.4% expanded overhead; its benefit is smaller category entry points and shared
common definitions. Content-addressed captures address repeated storage.

A separate read-only audit of historical retained evidence hashed regular files
and excluded symlinks. These are measured opportunities, not claimed deletions:

| Files selected by name | Files | Total bytes | Unique byte variants | Unique bytes | Exact duplicate bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| JSON filenames containing `schema` | 196 | 413,836,556 | 86 | 90,829,149 | 323,007,407 |
| `runtime.zip` | 1,824 | 2,292,296,768 | 181 | 173,303,960 | 2,118,992,808 |
| `plan.json` | 3,586 | 2,345,927,008 | 1,187 | 633,641,619 | 1,712,285,389 |

This filename-based audit does not claim to identify every embedded schema or all
duplicated native runtime files. Runtime downloads/builds and generated outputs
also occupy substantial historical storage. Schema duplication is one contributor.

## Contracts and limits

- Snapshot manifests retain provider, exact document version, declared
  authored/expanded flavour, SHA-256, byte count and a relative object reference.
  Reads verify saved bytes and the literal document version without regenerating.
- Identical concurrent captures publish complete files atomically. Different
  content cannot replace an existing named capture. Copy the whole store,
  including its `schemas/` directory, to relocate evidence.
- The bundle explicitly introduces relative file references in this opt-in
  format. Its manifest hashes every member; offline checking rejects missing or
  changed files, broken reference targets and malformed schema children.
- Readers have no upstream ports and a declared constructor file option. Source
  generators and other operations belong with filters; writer operations have
  their own category. Rendering validates one scene, readers/filters one node,
  writers one export. Common is a definitions library. The full entry point
  validates a complete document.
- Schema constraints, authored inline-node ID rules and literal annotation data
  are preserved. Category validators may refer to other categories through
  authored inline nodes or publication/readback settings. Graph resolution and
  native compatibility still require planning and execution.
- These tools are optional explicit commands. Existing capture consumers are not
  automatically redirected. The snapshot store captures whole-schema bytes; the
  bundle has a separate manifest. Neither provides automatic cache invalidation
  or rewrites execution receipts, plans or runtime archives.
- No existing historical evidence was deleted or rewritten. Hashes verify content
  identity, not authorship or native correctness. No native qualification was run.

See [schema usage and commands](../docs/schema-guide.md#portable-captures-and-paraview-category-bundles).
Generated reference artifacts are regenerated centrally after the combined changes.

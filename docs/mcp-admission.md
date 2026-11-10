# Catalogue admission contracts

The strict profile is generated from each installed built-in adaptor's
`admission.json`. Registration, discovery and readiness alone confer no access
to files. An adaptor-owned record declares its qualification references,
operation selection, complete input-file pointer patterns and unsupported
variants. The framework does not select an application by name.

Run `python3 tools/mcp_admission.py` after reviewing a contract or implementation
change. `python3 tools/mcp_admission.py --check` verifies that the committed
snapshot is current. Generation resolves the canonical registered schema;
there is no second hand-maintained admission schema. The snapshot pins that
schema, the registered route, the adaptor record and implementation, and shared
framework Python/JSON source. Runtime checks those pins before validating any
request, resolving inputs or calling an adaptor hook. Generating a snapshot is
a review step, not a native qualification or proof that an image is available.

Pointer patterns use JSON Pointer escaping and `*` for one array or object
member. A conditional slot resolves its discriminator at the same candidate
wildcard coordinates; a different node cannot authorise its input. They do not search recursively for fields that look like paths. Only
present declared slots produce capture requirements. Every leaf initially
contains an opaque capture identity; trusted binding replaces it with that
capture's exact immutable path. A caller cannot choose a path, executable,
module or mount by supplying a binding object. All optional file sources must
be declared too: sidecars, source images, track files, sprite timing metadata,
caption files and audio/video inputs are part of the closure.

`FileAdmission.input_slots(document)` validates the canonical schema and policy
without native imports or input I/O, then returns bounded `InputSlot` records.
The embedding resolves IDs within its owned task and performs full
`FileAdmission.check(document, context)` with trusted `InputBindings` before
capture leases or planning. It repeats the check with `bound=True` for saved
documents. Missing, additional, duplicate or overlapping bindings refuse.
The executor proves regular-file identity, digest and ownership separately;
slot discovery does not prove bytes safe or authorize host planning.

Literal workflow children use the same checks and `/operations/N/document`
pointer prefix. Workflow metadata references remain bounded by the shared
materialisation limits. A captured child must be literal: reference expansion
cannot silently create an input pointer. Cross-application output promotion is
an explicit trusted copy of a currently verified declared artifact, followed by
a new input capture; it does not grant access to the producer's workspace.

`FileAdmission.coverage()` reports admitted operation identities, contract
digests, limitations and routes missing file-access records. The first records
cover the full declared SymPy, NumPy, FFmpeg and ExifTool operation catalogues.
ParaView selects operations from passed native fixture and writer records;
failed writers and generated but unqualified declarations remain unqualified.
Qualification applies to the named historical fixtures and runtimes, not every
combination of options or an untested application release.

Installing an external adaptor plugin does not grant it the core distribution's
implementation pins. External package-resource closure is not yet qualified;
those routes remain visible as missing in coverage even if the plugin supplies
an admission record. The generator never imports such a plugin's schema hook.

The file-capture profile refuses folder scanning and saved metadata plans that
can contain indirect paths until their complete immutable closure is supported.
Explicit captured items and inline intent retain all declared metadata
operation families. ParaView source generators and qualified exports are
available without input files; PNG readers and textures use explicit capture
slots. Unresolved external reader families and OBJ's auxiliary `TextureFileName`
reference remain refused. ParaView axes, definitions, dimensions, views and
settings metadata sections are excluded from this literal graph profile. These limits are visible in coverage, rather than
being inferred as supported from native catalogue discovery.

Each capture slot declares a `contentPolicy`. `native` retains the reviewed
adaptor's existing parser contract. `hook` identifies a validator in that
adaptor's pinned package and literal validation options. Pure admission does
not import or call these byte validators. With `FileAdmission`, the trusted
executor supplies a `capturedContentPolicy` header containing the exact admitted
contract digests. The contained worker first proves every capture's immutable
descriptor, read-only mount and digest, checks that header against its installed
snapshot, then applies byte guards before planning or native parsing. It repeats
this sequence during capture planning, stale checks, execution and verification.
Custom operator-owned admission policies retain responsibility for their own
worker content checks; they do not inherit the strict MCP profile.

The qualified ParaView XML rectilinear-grid, structured-grid and table readers
use a closed VTK XML byte validator. The grammar accepts one inline ASCII numeric piece of a declared
rectilinear grid, structured grid or table. It refuses DTDs, entities, external
references, binary/appended arrays and companion-file formats. Bounds include
32 MiB, 65,536 elements, depth 32, one million numeric values/points/rows and
4,096 entries per structured axis. Array tuple/component counts must agree with
the declared structure, and integer/float literals must fit their native type.
Native readback remains responsible for verifying the actual dataset.

The three `pvGroupDatasets` output types have declared graph qualification with
exact native writer roundtrip type checks. The GenericIO particle fixture uses
qualified CellCenters and Tessellate operations to preserve vertex cells in an
unstructured grid before grouping. `pvGenericIOMultiBlockReader` is admitted
only in managed export readback; authored reader nodes and caller-selected
readback filenames are refused. See the compact [native qualification record](../verification/2026-10-30-paraview-closed-inputs.json)
for the frozen source, archive and image pins, successful cases, prior diagnostic
failures and the separate final MCP execution gate.

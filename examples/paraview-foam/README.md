# Real OpenFOAM slice MVP

Run from the repository root with Python 3.10+ and a discoverable ParaView 5.13.3
`pvbatch`. Set `PATH` or `SCHEMAXIS_PARAVIEW_ROOTS` to your installation; the adaptor
contains no installation path. Host Python needs no third-party packages.

```bash
export PYTHONPATH=src
export SCHEMAXIS_PARAVIEW_ROOTS=/path/to/paraview/install
python3 -m schemaxis.adaptors.paraview.mvp plan examples/paraview-foam/mvp.json
python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-foam/mvp.json --case-file cases/coupe-a/coupe_AMI.foam --output-directory coupe-001
python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-foam/mvp.json --case-file cases/coupe-b/coupe_AMI.foam --output-directory coupe-004
```

Each destination must be new and its parent must exist. The case files are read
only.

The two vehicle cases are not distributed with Schemaxis. `cases/coupe-a/...` and
`cases/coupe-b/...` are placeholders for your own decomposed OpenFOAM cases,
resolved from the current directory. Bind a case with `--case-file`, which
overrides `case.file` in `mvp.json` and `geometry.json`, or edit that value.
For geometry without rendering, use `geometry.json` with the same overrides.
File, stdin (`run -`) and Python callers use `schemaxis.core.documents.resolve_document`,
`Planner` and `Executor`; this is the existing `paraview.slice_export` provider.
The CLI prints the resolved document, authored-reference/expression provenance,
explicit overrides, defaulted plan, execution result and artifact digests.

For repeatable acceptance, including eight expected failures:

```bash
python3 examples/paraview-foam/acceptance.py --case-file cases/coupe-a/coupe_AMI.foam --case-file cases/coupe-b/coupe_AMI.foam --output-directory coupe-acceptance --failures
python3 -m unittest discover -s tests/unit -q
python3 -m unittest discover -s tests/conformance -q
```

`acceptance.py` invokes the same JSON CLI and retains every input, exact command,
report and native replay. Its `acceptance.json` is successful only after every
requested run/check succeeds. Without a discoverable runtime, native conformance
tests skip; the acceptance command requires a runtime and real inputs.

## What executes

The native OpenFOAM reader selects `Decomposed Case`, includes zero in its time
inventory, inspects regions and fields, and reads `internalMesh`. The example
selects times 0.8 and 1 exactly (`tolerance: 0`). Other time selectors use the
existing time helper and report approximations. U is a cell vector and p a cell
scalar. The reader also exposes interpolated point U/p. A reused cell-data
Calculator derives `Umag = mag(U)` before slicing; rendering and export checks use
**cell associations**. No scientific unit conversion is inferred.

The initial selected time supplies reference bounds. With midpoint `m`, normalised
normal `n` and projected half-width `h = sum(abs(n[i]) * (max[i]-min[i])/2)`, each
fraction `f` defines `origin = m + (2*f-1)*h*n`. The example fractions are
0.25, 0.5 and 0.75. These are fixed world-space planes for every selected time;
subsequent time-dependent bounds are inspected and reported, but do not move the
reference frame. The default normal is +x. A fraction outside the mesh can produce
an explicit `EMPTY_GEOMETRY` fault.

Position varies fastest, then time. All slice-property changes are applied before
dependent computation, including the position reset on time carry. One reader,
merge, calculator, slicer and surface filter persist throughout. Only time changes
update the upstream calculator explicitly; position changes update the downstream
slice. Native caching handles unchanged dependencies.

Each of the six geometry states exports one VTP **before** appearances/cameras.
Images show the slice and translucent exterior of the internal mesh, both coloured
by p, then both by Umag. The domain outline stays black. Each writer owns its size
and ordered camera samples. The example writer has four cameras, producing
`2 times × 3 positions × 2 appearances × 4 cameras = 48 PNGs`. Camera direction is
from the bounds midpoint towards the camera, with an explicit up vector and a
parallel projection sized to show the wind tunnel. ParaView's implicit first-render
camera reset is disabled. These are domain overview images, not vehicle close-ups.

## Evidence and supported limits

Each VTP is reopened. Verification checks nonempty geometry, finite coordinates
and fields, the requested plane, field associations/components/tuple counts,
`Umag` against U's magnitude, and matching full coordinate, polygon-connectivity
and U/p/Umag array hashes. Each PNG is decoded with VTK, checked for its writer's
dimensions and nonuniform pixels, and given a pixel digest. Native camera and
colour properties are read back. This verifies configuration and readable output;
it is not a perceptual image-quality score or CFD solver validation.

The host reconstructs the expected geometry visits and publication event sequence,
checks object identities, matching reopened evidence, coordinated colours,
writer-local camera ownership, dimensions and unique destinations. Acceptance
also checks 48 distinct image pixel digests per mesh and changing U/p data across
the two selected times. Counts and file existence alone do not certify success.

Native `verification.json` is replaced atomically after progress changes and is
marked successful only at the end. Failed runs keep their output prefix and exact
script. Timeouts preserve an incomplete receipt and a structured submission fault.
A retry requires a new directory. Artifact records contain SHA-256 file digests.
The exact submitted script includes snapshots of the pure-Python time/iteration
helpers, so native replay needs ParaView but no installed Schemaxis package. Replays
retain absolute input/output paths; CLI reruns against occupied destinations fail. Directly executing a retained script can write its recorded paths; use a new CLI destination for retries.

Supported mode is serial `pvbatch` reading all decomposed partitions. This does
not certify MPI execution, AMI interpolation correctness, arbitrary OpenFOAM
variants, or solver-specific dimensions/reference frames. The real-case branch
supports planar slices only; nonzero `origin`, synthetic `sweep` and crinkle mode
are rejected. Set `case.maxPublications`, `maxSlices` and `timeout` deliberately
for larger requests. Writer names and appearances must be distinct.

## Bounded authored expressions

An expression is an entire value of the form
`{"$expr": {"op": "overlay", "args": [base, overrides]}}`. The example composes
partial camera/writer/case templates before final argument validation and uses
arithmetic for fractions. `$document` operands retain their original definition
scope, including relative references.

Implemented operations take two arguments:

- `overlay`: replace supplied top-level keys wholesale.
- `merge`: recursive dictionaries, atomic arrays/scalars/null; optional
  `"conflict": "left" | "right" | "error"`, default left. Errors name the conflict
  path, and booleans do not equal numbers.
- `omit`: remove direct keys supplied by an array or object's keys.
- `get`: object/string-key or array/integer-index lookup; the key may itself be an
  expression. Numeric string keys and array indices are distinct.
- `add`, `subtract`, `multiply`, `divide`: finite scalar arithmetic.

No Python evaluation, native reflection or external file access occurs in these
expressions. Cycles, unknown operations, missing keys, invalid arithmetic and
excessive document expansion fault. Explicit named-list composition, general
vector/bounds expressions and references to arbitrary runtime field tuples remain
outside this implemented subset; bounds-derived slice placement is the bounded
native resource-inspection stage described above.

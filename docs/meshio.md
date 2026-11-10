# meshio: mesh interchange with explicit units

Convert a bounded, captured unstructured mesh between ASCII VTU and legacy VTK
4.2 while retaining ordered geometry, topology and point/cell arrays. This is a
general mesh interchange route for inspection and geometry handoffs. It does not
expose solver file formats or arbitrary meshio scripts.

## Contract and units

Use `schemaxis.meshio/1`, operation `convert`. Required fields are `source`
(absolute local regular `.vtu`/`.vtk` path), `sourceFormat` and `targetFormat`
(`vtu` or `vtk`), `sourceUnits` and `targetUnits` (`m`, `cm`, `mm`, `in`), and
`lossPolicy: "strict"`. Same-format unit conversion is also useful. Every field
is required; no units are guessed from an extension or from field names.

Coordinates are multiplied by source metres-per-unit divided by target
metres-per-unit, including the origin. For example mm to m multiplies XYZ by
0.001. Point/cell scalar and vector arrays retain their numeric values: vector
fields are **not** implicitly displacement, velocity or length. Convert their
physical units separately when needed. The summary labels tetrahedral and hexahedral volumes
in target length units cubed. A unit declaration is a user assertion, not an
independently measured property of the file.

Only triangle (VTK type 5), tetra (type 10) and eight-node hexahedron (type 12) cells are accepted, with exactly
three coordinates per point. Triangle cross-product magnitude must exceed
1e-12 times squared maximum vertex distance from its first vertex. A tetra's
signed determinant `(b-a)·((c-a)×(d-a))` must exceed 1e-12 times that distance
cubed: inverted, degenerate and nearly degenerate tetrahedra are refused. This
is a bounded orientation/degeneracy check, not a general mesh quality metric.
Point order and flattened cell order/connectivity must remain exact, including
interleaved triangle/tetra blocks. XML comments, block grouping and numeric storage dtypes may
change. No points are merged, reordered, repaired or remeshed.

Hexahedra use VTK node order and positive sampled trilinear Jacobians; see the
[geometry contract](meshio-hexahedron.md#geometry-contract) before use.

Data arrays require distinct names `[A-Za-z_][A-Za-z0-9_]{0,63}` and scalar or
three-vector tuples associated with every point/cell. Finite numbers are
required; integers are bounded by ±2^53 and compared exactly. Floating values
compare at relative 1e-11 and absolute 1e-14; byte formatting/dtypes are not a
preservation promise. Oriented triangle area vectors and signed tetra volumes
also compare at relative 1e-8 without an absolute floor, so small cells at a
large origin cannot pass from coordinate-relative tolerance alone. Float32 input values are interpreted at their declared IEEE
precision by the independent reader; integer values must fit the declared type.
meshio VTU ASCII uses about twelve significant digits, motivating the tolerance. XYZ magnitudes are at most 1e9 in both coordinate systems.

ASCII numbers use plain decimal syntax separated only by space, tab, CR or LF.
Digit-group underscores (`1_0`), hexadecimal, `nan`/`inf` words and other
control or Unicode separators are malformed content, refused before native
execution as `INVALID_MESH_CONTENT`; re-export the mesh as ordinary ASCII.

VTU XML bytes must be ASCII (no UTF-16 or NULs), containing a single `UnstructuredGrid/Piece` with inline ASCII DataArrays.
VTK must be 4.2 ASCII `UNSTRUCTURED_GRID`, using FIELD/FieldData point/cell
arrays. Binary/compressed/appended data, DTDs/entities, active
array attributes, extra metadata/sections, groups, sets, tensors, high-order
cells and unsupported arrays are refused before native execution. Bounds:
16 MiB source, 32 MiB output, 100,000 points/cells, 16 arrays per association.
The source plus output budget is consequently 48 MiB; retained JSON snapshots
also have a 32 MiB per-file bound. Native POSIX caps are 2 GiB address space,
32 MiB per file and 60 CPU seconds, within one configurable total deadline.

## Running and inspecting

Install meshio 5.3.5 plus NumPy in an isolated environment and configure its
absolute Python executable under application `meshio`, or pass `--meshio`.
The Schemaxis host does not import NumPy or meshio. The latest stable meshio
version is 5.3.5, checked against [PyPI](https://pypi.org/project/meshio/) on
4 November 2026. Native read/write uses the public
[meshio API](https://github.com/nschloe/meshio#python-library).

Start from [baseline](../examples/schemaxis/meshio-convert.json) or
[reverse conversion](../examples/schemaxis/meshio-convert-variant.json), replacing
the source path with the supplied literal fixture's absolute path. Use normal
`schemaxis plan INPUT`, `run INPUT --output-directory OUTPUT --meshio PYTHON`
and `verify OUTPUT`. Studio offers editable conversion and reverse-conversion
starters, source forms and contextual Help.

The output includes `mesh.vtk` or `mesh.vtu`, `mesh-summary.json`, captured source,
authored/effective plans, native scripts/configuration, stdout/stderr/submissions,
consumed-input digests and a verification record. Inspect bounds, ordered counts,
array names and signed tetra/hexahedron volumes in the summary; use a compatible viewer for
geometry. Two isolated native processes perform conversion and fresh reopening.
Standard-library reference readers independently parse original and output bytes
and check the unit transform, ordered topology and data. Fresh meshio reopening
is an additional consistency check. Offline verification rechecks retained
artifacts/evidence without rerunning meshio and is not a signed anti-forgery proof.

## Workflows, reuse and recovery

Verified geometry artifacts can feed another meshio conversion through the
normal workflow artifact reference; explicit format/units must agree with the
producer. Source byte hashes govern reuse: editing a source at the same path
invalidates reuse. Finite studies can vary targetUnits/targetFormat through the
shared expression and axis model. No time-series, MPI, live native editing or
interactive native inspection is exposed.

`INVALID_MESH_SOURCE` means choose an absolute matching regular file, with no
symlink. `INVALID_MESH_CONTENT` explains the unsupported section, numeric shape,
orientation or bound; export supported ASCII data instead of discarding it.
`INTERPRETER_NOT_FOUND` requires the configured isolated interpreter. Native
version errors require meshio 5.3.5. `VERIFICATION_FAILED` means inspect retained
logs and original source; a successful process or merely existing mesh does not
satisfy preservation. Cancellation and timeout retain failed/incomplete evidence
and terminate the owned subprocess tree.

Qualification uses literal fixtures with nonzero origin, interleaved cells,
positive tetra volume 4 mm³, distinct scalar IDs/regions and three-vector point
and cell arrays. Baseline converts mm to m; the reverse variant restores mm.
The bounded release does not claim other meshio formats or binary-file support.
See [hexahedral volume interchange](meshio-hexahedron.md) for the complete added
CAE volume scope, geometry checks, native mapping, examples and handoff.

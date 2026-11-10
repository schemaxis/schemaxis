# Hexahedral CAE volume interchange

Convert an eight-node hexahedral volume mesh between ASCII VTU and VTK 4.2,
including mixed triangle and tetrahedral cells, with explicit coordinate units.
This extends the existing `schemaxis.meshio/1` `convert` contract; all fields are
required and unchanged. The host reads files independently before native execution,
then compares both output bytes and a fresh isolated meshio reopening. See the
[main guide](meshio.md) for resource limits, fields, units, losses and recovery.

## Geometry contract

Use VTK type 12, with four base corners `(0,1,2,3)` oriented toward the opposite
face `(4,5,6,7)`, and corresponding edges `0–4`, `1–5`, `2–6`, `3–7`. These are
local connectivity positions, not point IDs. A Cartesian brick is ordered
`(0,0,0), (a,0,0), (a,b,0), (0,b,0), (0,0,c), (a,0,c), (a,b,c), (0,b,c)`
for positive a, b and c. Affine shear and trilinear warping are supported;
points, ordered connectivity and all supported point/cell tuples retain their
original association. A valid cyclic reordering still fails preservation.

The standard-library oracle differentiates the eight trilinear shape functions
on `[-1,1]^3`. At each of the eight corners, the centre and eight two-point Gauss
locations, the signed Jacobian determinant must exceed `1e-12 L^3`, where L is
the largest distance from corner 0 to another corner. Coordinates are translated
before differentiation to reduce cancellation at large origins. Repeated IDs,
nonfinite coordinates, sampled inverted/folded and nearly collapsed cells fail
as `INVALID_MESH_CONTENT` before native assignment. Source and output coordinate
systems must both satisfy the check.

**These 17 positive samples do not prove global Jacobian positivity.** They do
not certify convexity, nonintersection, face planarity, neighbouring-cell
conformity, a valid volume partition or engineering mesh quality. Assess those
properties with an appropriate mesh-quality tool before analysis. Conversion
does not repair or remesh a cell. Triangles and tetrahedra retain their previous
orientation/degeneracy contract.

`hexahedronVolumes` in `mesh-summary.json` lists signed volumes in flattened
hexahedron order, in `volumeUnits` (target length cubed). Tensor two-point Gauss
quadrature integrates the trilinear signed determinant exactly in mathematical
arithmetic because its degree is at most two in each reference coordinate.
This is an isoparametric volume convention even when faces are warped. Every
sampled determinant must also survive conversion at relative `1e-8`, without
an absolute tolerance floor, in addition to coordinate/data checks. Volume is
a derived geometric check, never a field-unit conversion.

## Native mapping and public sources

The public meshio API is `meshio.read`, `Mesh.points`, `Mesh.cells`, `point_data`,
`cell_data` and `meshio.write(binary=False)`. The worker admits the
`hexahedron` CellBlock type and writes `vtu` or `vtk42`. It preserves native
cell-block order while flattening, and refuses field data, point/cell sets and
periodic metadata. Two isolated processes read the captured source and reopen
the output. Native and independent snapshots must agree.

Reviewed 4 November 2026: [PyPI release metadata](https://pypi.org/pypi/meshio/json)
reports stable meshio 5.3.5; its
[tagged VTK cell mapping](https://github.com/nschloe/meshio/blob/v5.3.5/src/meshio/_vtk_common.py)
maps type 12 to `hexahedron` without a node-order permutation. The
[public library API](https://github.com/nschloe/meshio#python-library) documents
read/write and Mesh fields. The
[VTK hexahedron declaration](https://github.com/Kitware/VTK/blob/master/Common/DataModel/vtkHexahedron.h)
defines corner order and standard isoparametric shape functions. Native
qualification records the observed meshio/NumPy runtime separately from this
API review. Discovery and planning never import either library.

## Editable examples and a useful handoff

[Baseline](../examples/schemaxis/meshio-hex-convert.json) reads the supplied
[affine shear fixture](../examples/schemaxis/fixtures/meshio/hex-affine.vtu),
converts mm to m and writes VTK. Its hex volume is 24 mm³ (24e-9 m³).
[Held-out variant](../examples/schemaxis/meshio-hex-variant.json) reads the
[warped fixture](../examples/schemaxis/fixtures/meshio/hex-warped.vtk), converts
cm to mm and writes VTU. Its Cartesian top corner is raised by 1 mm, adding
`2 * 3 * 1 / 4 = 1.5 mm³` to the 24 mm³ brick. Expected volume is 25.5 mm³.
Both fixtures contain 12 points, a hex, a boundary triangle and a disconnected
positive tetra of 4 mm³. They exercise mixed cells and field associations;
they are demonstrations, not a conforming single-domain solver mesh.

Replace `source` with the fixture's absolute path, then use `schemaxis plan`,
`run --meshio PYTHON --output-directory OUTPUT` and `verify OUTPUT`. Studio's
“Hexahedral volume mesh to metre VTK” starter offers the same editable intent.
Inspect counts, bounds, arrays and signed volumes before handing the published
geometry to a viewer. Physical scalar/vector fields, including displacement,
keep their numbers; convert their units separately when necessary.

`tools/qualify_meshio_hexahedron.py` runs the four retained/added native cases,
literal output oracles, valid-topology reordering and field/native-geometry
tampering with refreshed receipts, malformed/high-order/voxel refusals, and a
verified metre-VTK-to-centimetre-VTU workflow with reuse. With `--gmsh PYTHON`,
it also opens the actual verified VTK artifact in isolated Gmsh, reads nodes
and element types/order, and integrates the hex volume using Gmsh's public
`getIntegrationPoints`/`getJacobians` APIs. This is an independent consumer
handoff for geometry and volume only; no Gmsh group/field preservation is claimed.

## Capability families and exclusions

| Family | Implemented and verified | Remaining scope |
| --- | --- | --- |
| Static volume interchange | ASCII VTU/VTK 4.2; triangle, tetra, eight-node hex; mixed flattened order | Wedge/pyramid/voxel, quads, polyhedra and high-order cells |
| Geometry semantics | Explicit m/cm/mm/in units; nonzero origins; bounded orientation/Jacobian checks; signed volumes | Global positivity proofs, quality certification, intersections and repair |
| Field preservation | Distinct scalar/three-vector point/cell arrays; exact integer values; documented float tolerance | Tensor, complex, string and ragged arrays; implicit field-unit inference |
| Workflow handoffs | Captured geometry artifacts, verified consumer input, source-byte reuse/invalidation, finite studies | Solver case preparation/execution, native scenes, live editing, time series and MPI |
| Format breadth | Two independently parsed ASCII interchange formats | Gmsh MSH and physical groups/IDs, solver formats, binary/compression, arbitrary metadata/sets |

`INVALID_MESH_CONTENT` for a hex usually means incorrect VTK order, collapsed
corners, sampled inversion or an unsupported cell type. Inspect the source and
export an explicitly supported topology; changing only a cell-type label is
invalid. `VERIFICATION_FAILED` after native execution means inspect retained
source, native logs, ordered arrays and publication digests; never infer success
from a file's presence. Resource, timeout, cancellation and runtime recovery
follow the main guide. Unsupported groups/metadata are refused, never discarded.

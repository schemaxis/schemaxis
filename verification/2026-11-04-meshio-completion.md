# meshio hexahedral volume completion — 4 November 2026

Reviewed scope: extend `schemaxis.meshio/1` convert from triangle/tetra to include
VTK-order first-order eight-node hexahedra in ASCII VTU and VTK 4.2. This is a
complete bounded interchange extension, not full meshio format coverage. The
[capability-family map](../docs/meshio-hexahedron.md#capability-families-and-exclusions)
retains gaps and defines the product boundary.

| Checklist | Result and evidence |
| --- | --- |
| registration | Existing route/runtime/runner retained; declared execution remains serial isolated meshio 5.3.5, no host native import. Manifest/discovery now distinguish hex CAE volume interchange. |
| schema | No authored fields/options/defaults change; source/target format, explicit units, source path and strict loss policy remain required. Existing immutable planning/schema checks plus new topology tests pass. |
| semantics | Independently parse VTU type 12 / legacy 8-node cells. Exact VTK node order; 17 positive relative-threshold Jacobian samples; repeated, sampled inverted/twisted/folded/near-degenerate geometry refused. Both source and scaled geometry validated. Sampling is explicitly not a global positivity, convexity, conformity or quality proof. |
| native-mapping | Public `meshio.read`, `Mesh.points/cells`, point/cell arrays, `meshio.write(binary=False)`; type `hexahedron` admitted. Independent readers check ordered topology and values; separate process reopens output. Tagged meshio 5.3.5 public VTK mapping and VTK corner/shape-function declaration reviewed. |
| execution | Existing source capture, hashing, publication membership, process deadlines/cancellation/caps, logs and independent offline verification retained. Source/output sampled Jacobians compare at relative 1e-8. Signed isoparametric hex volume uses exact tensor two-point Gauss integration (floating arithmetic). No physical field units inferred. |
| discovery | Curated hex/brick/CAE volume terms and reviewed positive “hexahedral volume interchange” plus negative solver query; existing ambiguous mesh and unrelated negative cases retained. Capability and Studio search regressions run separately. |
| guidance | All ten operation/field records reviewed; no pending/stale records. Operation/source guidance explains eight-node cells, units, preservation and sampled-validity limitation; structural schema addresses unchanged. |
| help | Main guide links added geometry contract, public API review, examples, field/volume conventions and recovery. Packaged Help/reference generation is shared and rerun by the integrating owner. |
| examples | Affine mm→m VTU→VTK hex (24 mm³) and held-out warped cm→mm VTK→VTU hex (25.5 mm³), each 12 points with triangle/tetra and scalar/vector arrays; editable Studio starter. Literal expected points/cells/fields/volumes do not derive from native output. Fixtures illustrate mixed cells, not a conforming solver-domain partition. |
| tests | Focused meshio host suites pass (16 tests). Native acceptance retains old triangle/tetra cases and adds two hex cases, malformed/high-order/voxel and inverted/twisted/folded/thin preflight refusals, native high-order refusal, refreshed-receipt topology/field/native-geometry tampering, workflow handoff and unchanged reuse. |
| qualification | Bounded native four-case conformance and independent extension acceptance pass under meshio 5.3.5. Gmsh 4.15.2 independently opens verified metre VTK, checks node/element order and integrates volume 24e-9 m³. Gmsh field/groups are outside this consumer claim. Canonical receipt is registered after final source and metadata changes. |
| maintenance | Latest stable PyPI metadata still 5.3.5 on 4 November 2026; absorbed version unchanged. Assessment scope/rationale reviewed with a new dated checkpoint, breadth 10% and abstraction 60% unchanged: extra supported topology does not imply broad format coverage. Accepted historical baselines remain unchanged. |

Local bulk evidence is ignored under `evidence/cae5-meshio/`: `hex-native2`
contains the successful complete extension run, kit receipt, hostile controls,
workflow and Gmsh consumer logs. First development run `hex-native1` exposed a
qualification mutation's whitespace assumption; the mutation was corrected
without changing application verification, and the entire extension run repeated.
Native output uses scalar arrays separated by spaces, unlike connectivity rows.

Primary sources reviewed: [meshio release metadata](https://pypi.org/pypi/meshio/json),
[public library API](https://github.com/nschloe/meshio#python-library),
[tagged cell mapping](https://github.com/nschloe/meshio/blob/v5.3.5/src/meshio/_vtk_common.py),
[VTK hexahedron declaration](https://github.com/Kitware/VTK/blob/master/Common/DataModel/vtkHexahedron.h),
and [Gmsh mesh API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002fmesh).
The rendered VTK class page was unavailable to the browsing tool; its public
source declaration supplied the corner order/shape-function contract instead.

Not applicable decisions remain those already declared: no MPI, live editing,
interactive native inspection, time batches or native scene save. Groups/sets,
metadata, quadrilateral surfaces, wedge/pyramid/voxel/high-order cells, solver
formats and binary/compressed payloads remain explicit exclusions. Host admission
is structural evidence; successful native cases prove only named fixtures and
recorded runtime/lifecycle scope, not all possible warped cells.

Executed checks: `test_meshio*.py` 16/16; `studio_guidance.py --app meshio
--check` ten reviewed, no pending/stale; readiness admission passed; retained
`tools/qualify_meshio.py` passed Float32/nonround-large-origin cases, hostile
artifacts, native parser negatives, active cancellation, workflow same-path
source invalidation and finite composition. `test_adaptor_assessments.py` passed
20/20 including real generated-index parity; production Studio search passed
515/515, including the new hex phrase and negative solver phrase. Reference,
packaged Help and assessment generator checks passed after generating assessment
before final Help packaging. The first ordering packaged Help before assessment
and correctly detected two stale topics; regeneration repaired the ordering.
Generated/shared files were restored after verification in this isolated branch;
the integrating owner regenerates and verifies final shared output. Bulk logs:
`generated2`, `retained-native` and `hex-native2` under the local evidence prefix.

Final private-branch `adaptor conform schemaxis.meshio/1 --native` (`canonical`)
passed all four named cases and lifecycle controls; its qualification was
registered with matching current source digest. Observed meshio 5.3.5 / NumPy
2.5.4, Gmsh consumer 4.15.2. Assessment freshness and final admission pass.
The integrating owner must repeat canonical qualification after shared generation
because packaged Help is deliberately part of the conservative source identity.

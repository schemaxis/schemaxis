# OpenSees planar truss engineering

The `schemaxis.opensees/1` document assesses a planar pin-jointed elastic
structural network. Describe nodes, Cartesian restraints, axial members, nodal
loads and named measured limits. The adaptor constructs the solver model,
checks network stability before launch, runs one full static load increment and
independently checks every displacement, reaction, member force and stress.

## Start and edit

Start with `examples/schemaxis/opensees-triangle.json`, or choose **Planar truss
serviceability** in Studio. The redundant example includes a fourth node, mixed
member stiffness and statical redundancy. Uplift/lateral and doubled-area variants
exercise signed response and redesign. Change node coordinates, member endpoints,
Young's modulus or area, restraints, loads and requirement limits with ordinary
JSON pointer edits. Replanning never mutates the authored document. Studio offers
complete document controls, templates, Help and undo; execution uses fresh native
processes rather than persistent solver objects.

Configure an absolute Python executable containing OpenSeesPy 3.8.0.0 with
`schemaxis configure`, `--opensees`, or `OPENSEES_PYTHON`. The observed engine must
report OpenSees 3.8.0. Host discovery, schema, planning and verification never import
OpenSeesPy. Run a document with `schemaxis run INPUT --output-directory NEW` and
recheck retained evidence with `schemaxis verify NEW`.

## Physical conventions

Use metres, newtons, square metres and pascals. Coordinates and force components
are global x/y. A node's `fixed` pair restrains x then y translation; omission
means both are free. Restraints impose zero displacement. Every member connects
two distinct declared nodes and has its own positive E and area. Members are
straight two-node axial bars; intersections create joints only when a shared
node is explicitly authored. Parallel coincident members must be combined into
one equivalent axial stiffness. Nodes must each belong to a member. Disconnected
components are allowed only if each is independently restrained and the assembled
system passes the same stability test. Fixed-only components cannot create free
rigid-body modes. Every model needs at least one free degree of freedom and a
nonzero nodal load; each node appears in the loads array at most once.

Positive member force/stress means tension; negative means compression. Positive
support reaction acts along the positive global axis. Member extension divided
by original length is engineering axial strain. Requirements use displacement
vector magnitude at one named node, or absolute axial force/stress at one named
member. `maximum` uses the selected quantity's SI unit. A passing stress limit is
a user-authored elastic measurement decision, not a yield, buckling or code check.

The bounded product permits 2..40 nodes and 1..80 members, coordinates within
+/-10000m, forces within +/-10000 N per component, E 1e6..1e12 Pa and area 1e-8..1 m².
Member lengths must reach 1e-6m. Scaled Cholesky pivots below 1e-9 reject mechanisms
and severe conditioning. Independent axial strains must remain <=0.001 and each
node's displacement <=1% of its shortest incident member. These are modelling
limits, not general guarantees of structural safety.

## Verification and deliverables

A dependency-free host assembles the Cartesian direct-stiffness matrix and
solves the restrained system with diagonally scaled Cholesky. This is independent
of OpenSees model construction, numbering, linear algorithm and FullGeneral
solver. It checks every native displacement, reaction, signed axial force/stress,
strain and length to relative 1e-7 with absolute floors 1e-12m/strain and 1e-6N/Pa.
Native force/moment equilibrium must also close within 1e-7 of the force/lever-arm
scale. Numeric CSV cells are independently compared to these checked responses.

The retained `model.json` contains editable physical records. A second isolated
process reconstructs and solves this exact retained model; results and runtime
must agree. This proves repeatable reconstruction, not native OpenSees database
save/restore. Native queries read node/element identities, coordinates, member
connectivity, fixed DOFs, material tangent and member axial response. Native basic axial stiffness EA/L divided by the independently queried tangent
and multiplied by length supplies area even when member force is zero.

`displacements.csv` holds one-based node index, ux,uy,rx,ry; `members.csv` holds
one-based member index, length, signed force, stress and strain. Array order in
`model.json` maps each numeric index to the authored ID. Preserve
`truss-assessment.json` for units, full identities, numerical checks, named
requirement observations, margins, acceptance and explicit losses. Both CSVs
are ordinary workflow `table` publications usable by spreadsheet adaptors;
retain the model and assessment when transferring them. No implicit conversion
or units inference is performed. Self-contained authored identity and independent
saved verification govern scheduler reuse; edited geometry/material/load must
produce a fresh attempt. Shared composition resolves ordinary expressions before
physical planning.

The triangular baseline has A(0,0),B(2,0),C(1,1), A fixed, B y-restrained,
E=200GPa and area=0.001m². A 1000 N downward apex load gives reactions 500 N upward
at A/B, diagonal compression -500√2N and horizontal tension 500 N. Virtual work
and compatibility give ux(B)=5e-6m, ux(C)=2.5e-6m and
uy(C)=-(√2+0.5)*5e-6m. Doubling every area halves displacement and stress while
preserving these statically determinate member forces. These literal witnesses
are authored independently of observed solver output.

## Faults and recovery

`INVALID_TRUSS` identifies bad IDs, missing endpoints, incompatible dimensions,
small-strain violations or missing loads; correct the located physical record.
`UNSTABLE_TRUSS` identifies a mechanism or severe conditioning; revise restraints
or add physically appropriate bracing. `INVALID_REQUIREMENT` identifies a target
of the wrong kind. `PERFORMANCE_NOT_MET` preserves measured margins and fails the
attempt; change the explicit design or bound and rerun in a fresh directory.
`INTERPRETER_NOT_FOUND` requires an absolute usable Python with the pinned package.
`NATIVE_EXECUTION_FAILED` retains native stdout/stderr and submission records;
inspect these and install the qualified runtime. `RUNNER_TIMED_OUT` and
`RUNNER_CANCELLED` preserve incomplete evidence, never a reusable success.
`VERIFICATION_FAILED` rejects missing, modified, excessive or inconsistent files;
preserve the failed attempt and rerun a fresh one. Existing output directories
are refused. No fault silently changes load, support, material or requirements.

## Capability-family map

| Upstream family | Intended product coverage | Implemented/verified scope | Explicit exclusions and next families |
| --- | --- | --- | --- |
| Geometry and constraints | Editable engineering network records | General bounded2D nodes/members, Cartesian zero restraints, redundant networks, stability |3D, multipoint constraints, settlements and general mesh import excluded |
| Materials and elements | Per-member elastic stiffness | Elastic uniaxial material and axial Truss; E/area/native responses read back | Frame/shell/solid elements, plasticity, damage, fibre sections and cables excluded |
| Static loads and solution | Signed nodal serviceability | Arbitrary bounded nodal x/y load superposition, direct native static solve, independent stiffness/equilibrium | Distributed loads, prestress, geometric nonlinearity, instability and failure excluded |
| Decision and handoff | Traceable measurements and editable redesign | Named node displacement/member force/stress limits; model, CSV and assessment publications; workflow reuse | Code compliance, optimisation and certified safety decisions excluded |
| Dynamics/geotechnics | Outside this product | No implementation or qualification claim | Earthquake histories, modal/transient analysis, soil/foundation coupling, damping, contact, MPI and reliability excluded |

The delivered product is complete within the stated planar elastic truss scope.
It covers a small subset of OpenSees as a whole. Further development should reuse
node/member/load/measurement records while introducing separately reviewed frame
or dynamic families; operation counts do not establish whole-application breadth.

## Public API and release basis

The official [OpenSees distribution](https://opensees.berkeley.edu/OpenSees/user/download.php)
and [3.8.0 release](https://github.com/OpenSees/OpenSees/releases/tag/v3.8.0)
identify the current stable engine. [OpenSeesPy on PyPI](https://pypi.org/project/openseespy/)
identifies3.8.0.0. API mappings follow the public
[truss command](https://openseespydoc.readthedocs.io/en/latest/src/trussEle.html),
[elastic truss analysis](https://openseespydoc.readthedocs.io/en/latest/src/truss.html),
[output commands](https://openseespydoc.readthedocs.io/en/latest/src/outputcmds.html),
[fixed DOF query](https://openseespydoc.readthedocs.io/en/latest/src/getFixedDOFs.html)
and [model print](https://openseespydoc.readthedocs.io/en/latest/src/printModel.html).
Documentation version banners lag the distribution; native3.8.0 API probes and
bounded acceptance establish the exact observed mappings. Readiness, documentation
coverage, runtime availability and source-bound qualification remain separate axes.

Native package import failure is `NATIVE_UNAVAILABLE`; a different engine or
package version is `UNSUPPORTED_RUNTIME`. Install the pinned package in the
configured isolated interpreter and rerun fresh. Native observation records both
engine3.8.0 and package3.8.0.0; neither is inferred from an executable filename.

`examples/schemaxis/opensees-workflow.json` demonstrates scheduled execution.
An unchanged verified attempt is reused. Corrupted output requires a fresh native
attempt; changed authored workflows require a new workflow directory rather than
silently resuming a different model.

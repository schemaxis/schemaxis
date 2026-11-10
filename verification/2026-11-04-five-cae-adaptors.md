# Five CAE adaptors — 4 November 2026

This integration adds OpenSees and Elmer and completes extensions to FreeCAD,
meshio and Cantera. Discovery exposes 49 application providers and 55 authorable
routes, including 54 workflow-embeddable document alternatives. Completion applies
to the declared product scopes below; each guide retains a capability-family map
and explicit broader-application exclusions.

| Adaptor | Delivered product scope | Canonical native cases |
| --- | --- | ---: |
| OpenSees (new) | Bounded planar elastic truss networks, mixed stiffnesses, signed loads/restraints, reactions, member stresses and measured serviceability requirements | 5 |
| Elmer (new) | Layered steady solid heat conduction, uniform sources/sinks, value/flux/convection ends, saved-field reopening and sampled requirements | 8 |
| FreeCAD | Editable finite-depth and through-all machining, persistent depth drivers, blind recesses and counterbores, saved-history and exchange verification | 9 plus 2 assembly controls |
| meshio | Strict first-order hexahedral VTU/VTK interchange, unit transforms, ordered topology/fields, sampled Jacobian preservation and signed volumes | 4 |
| Cantera | Closed constant-pressure/constant-volume reactor histories with optional fixed-bath thermal exchange, independent energy/species dynamics and explicit temperature-rise interpretation | 16 |

## Verification

- Fresh source-bound native conformance passes all **44 cases across six routes**,
  with canonical publication/input integrity, timeout and prelaunch cancellation
  controls. Portable receipts retain source/case digests and observed versions.
- Independently selected integration probes pass: translated skew-hex inch/metre
  conversion, an unequal-stiffness axial chain with opposing loads, source/sink
  thermal layers with inflow and convection, affine-driven rectangular CAD pockets,
  and two-atmosphere inert-gas heating for both reactor models. Unmet criteria,
  malformed geometry and inapplicable depth are refused.
- Native metadata rejects boolean-as-numeric forgeries after ordinary hashes are
  refreshed. The existing scaffold native-import guard remains unchanged; Elmer's
  pure host SIF/mesh readers are in `formats.py`.
- Full host suite: **5,114 tests run, 373 explicit skip results, zero failures/errors**.
  The inventory contains 5,435 unique test method IDs across 345 modules;
  class-level skips explain the difference from `unittest.testsRun`. Three
  disjoint whole-module groups exactly match ordinary full discovery; no tests
  are omitted or duplicated.
- Full Studio suite: **814 tests, 811 passed, 3 skipped, zero failures** on repaired
  frozen source, including browser tests and production search.
- All five admission checks, six host conformance sets and six guidance audits
  pass. Reference/schema generation checks 172 files; assessment parity and all
  1,491 packaged Help topics are current.
- A fresh isolated wheel installation discovers all 49 providers and plans
  all five delivered adaptor scopes without native application dependencies.
  Source, wheel and source-archive neutral release scans pass. The tested
  distribution source is commit `9cdcafc25b00cf0f844e804b064a9ed9364bde04`;
  the source implementation tested by the full host suite is
  `d06fd4afb0a732eb09a2e74dcf8288d0c6fee7b1`. The intervening commit registers
  the successful native receipts without changing the implementation.
- The unmodified neutral release gate passes. A separate unchanged private scan
  has the same inherited findings on the starting commit and integrated source;
  this batch introduces zero additional findings. That scan is not relabelled a
  pass, and no public publication is part of this integration.

Observed native versions: OpenSees 3.8.0 / OpenSeesPy 3.8.0.0; Elmer 26.2 from
stable 26.2.1 source (the binary does not report patch precision); FreeCAD 1.1.4;
meshio 5.3.5 with NumPy 2.5.4; Cantera 3.2.0. The optional mesh consumer was Gmsh
4.15.2. Qualification is serial and fixture-bounded, not an exhaustive upstream,
MPI, experimental-validity or structural-safety certification.

## Bounds

Elmer remains one-dimensional constant-area, constant-property solid conduction;
its native ASCII VTU exports have eight significant digits, with full-precision
restart-backed tables and a prelaunch coordinate-separation guard. Its limits
apply to declared mesh samples. OpenSees excludes bending, buckling, nonlinear
materials and dynamics; fresh model reconstruction is distinct from native
project/database persistence.

A finite FreeCAD cut can pass through thinner stock while retaining finite-depth
intent. Hexahedral positive Jacobian samples do not prove global cell validity.
Cantera remains the pinned ten-species hydrogen/oxygen mechanism: a hot bath can
cause an inert temperature-rise crossing, so that criterion does not establish
chemical ignition. Strong cooling retains strict nonnegative-species checks and
may require an explicitly tighter solver tolerance. Whole-application breadth
and workflow abstraction remain separate subjective assessments.

After integration, the pre-existing uncommitted application-module work was
preserved and shared references and Help were regenerated. The combined checkout
was separately pinned as `bf4e13c7de18125f06a6611c2ada94bf2e08c944`: all **44 native
cases**, **815 Studio tests (812 passed, 3 skipped)** and **151 focused host tests
(1 skipped)** pass with zero failures/errors. This snapshot is separate from the
accepted implementation commits; it does not commit that pre-existing work onto
the development branch. Registered native receipts bind the clean accepted
source; combined-checkout qualification is retained separately.

No version bump, push, deployment or public release is part of this work.

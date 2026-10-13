# CalculiX elastic cantilevers

`schemaxis.calculix/1` turns a rectangular beam, an isotropic elastic material
and a signed end force into a measured linear static cantilever assessment.
`cantileverBeam` derives C3D20R quadratic solid meshes and rejects a solve unless
separate axial and transverse refinement, support equilibrium and independent
slender-beam checks pass. Named requirements assess the actual checked native
outputs; a valid solve can fail its serviceability limits.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/calculix-beam.json \
  --calculix /absolute/path/to/ccx --output-directory evidence/my-beam
PYTHONPATH=src python3 tools/qualify_calculix.py \
  --executable /absolute/path/to/ccx --output-directory evidence/my-qualification
```

The target is official stable **CalculiX 2.23**, listed by the
[solver author](https://www.dhondt.de/) and [project](https://www.calculix.de/).
Its public [2.23 HTML manual](https://www.dhondt.de/ccx_2.23.htm.tar.bz2)
documents C3D20R, `*CLOAD`, `*NODE PRINT`, `*EL PRINT` and the solver CLI.
The official Linux binary's `-v` prints `This is Version 2.23` and exits 201;
the adaptor handles that exact convention locally within the shared process
supervisor. Other exits or versions fail. No native modules enter host planning.

## Physical model and declared limits

All lengths use **m**, force **N**, Young's modulus/stress **Pa**, and moment
**N m**. The beam extends along positive x. Its rectangular section is centred
at y=z=0; width is along y and height along z. The complete x=0 face is fixed
in all three displacement directions. The signed `tipForceZ_N` acts in global
z on the x=length face; there are no other loads. A negative force bends down.
Uniform end shear is represented by consistent quadratic face integrals:
corner nodes carry -1/12 and midside nodes +1/3 of each face's force. These
negative corner weights are the integrated serendipity shape functions, not
separate physical reverse tractions. Shared face nodes receive assembled weights.

This is a bounded idealisation, requiring domain review before engineering use:

| Property | Authored domain |
| --- | --- |
| Beam length | 0.001–10 m |
| Width and height | 0.00001–1 m |
| Length/max(width,height) | 20–40 |
| Width/height | 0.5–2 |
| Young's modulus | 1e6–1e12 Pa |
| Poisson ratio | 0–0.35 |
| Absolute signed force | 0.01–1e8 N |
| Independent theory displacement/length | at most 0.01 |
| Independent engineering root normal stress/E | at most 0.001 |
| Base axial cells | 12–24; default 12 |
| Base cells along each section direction | 2–3; default 2 |
| Base axial cell/minimum transverse cell | at most 10 |

The small-deformation and strain bounds define a linear analysis domain; they
do not establish any material's yield strength. The generated deck declares only
elastic behaviour. Plasticity, buckling, dynamics, contact, thermal effects,
general geometry and arbitrary imported decks are unsupported.

## Independent numerical acceptance

Each attempt runs base `nx × n × n`, axial-refined `2nx × n × n` and
fully refined `2nx × 2n × 2n` meshes. The largest fine mesh has 1728 elements and 8869 nodes.
The retained `beam.inp` is the fine editable deck. A fourth independent process
reopens its exact bytes and must reproduce its complete native DAT output.

The host parses one complete static step with exact tip/root node membership
and eight integration points per element. It independently reconstructs
Gauss-point coordinates from authored dimensions and mesh, then checks native
coordinates within 1e-6 of each global dimension. Finite stresses are measured
at those actual coordinates. No authored solver commands or deck cards exist.

With I=width×height³/12, the independent Euler–Bernoulli reference is
Uz=F×length³/(3EI). Actual tip Uz is an **area-weighted mean**, using the same
integrated face shape functions as the load. It is neither maximum nodal
displacement nor the displacement-vector magnitude. Each refinement must change
that mean by at most 1% of the absolute theory reference; the fine mean must be
within 3% of it. Small area-mean axial/lateral displacements are also checked.

Native `RF` prints external force, including loading and reactions. This recipe
has no CLOAD at root nodes and no DLOAD, so root RF is actual support reaction.
The host sums individual native root forces and r×RF about the **clamp centre
(0,0,0)**. Expected reaction is(0,0,-F); expected support moment is(0,F×L,0),
balancing the load's moment(0,-F×L,0). Each component residual must be at most
1e-4 of |F| or |F|×L. This accommodates cancellation in six-digit printed forces.

For every native Gauss point with x/L in [0.3, 0.7], normal stress Sxx is compared
against -F×(L-x)×z/I. Error is at most 5% of that section's analytical **surface
stress scale** |F|×(L-x)×height/(2I), avoiding division by near-zero neutral-axis
stress. This region excludes clamp/end Saint-Venant effects. It does not assess
root stress concentrations, surface maxima, von Mises/yield, fatigue or failure.
The acceptance tolerances are explicit modelling limits, not claims that beam
theory exactly reproduces a three-dimensional fully fixed elastic clamp.

## Outputs and requirements

Stable artifact order is 0: `beam.inp` (editable text), 1: `interior-stress.csv` (numeric
table) and 2: `beam-assessment.json` (text). The CSV has element/integration-point
IDs, x/y/z in m, and Sxx/Syy/Szz/Sxy/Sxz/Syz in Pa, only within the interior
sampling window. Its finite numeric cells can be reused through normal workflow
artifact references. Full native DAT/FRD/STA and command logs remain in the
attempt directory. Verification reconstructs intended decks, measurements,
requirements and publication hashes before reuse; altered deck geometry fails
even when its declared hash is refreshed.

Requirements have unique lowercase names, `quantity` and a nonnegative
`maximum`. `absTipAreaMeanUz_m` limits the absolute **area-mean z displacement**.
`maxInteriorSampleNormalStress_Pa` limits the largest absolute Sxx among fine
native Gauss samples in the interior window. The latter is mesh/sample dependent
and is explicitly not an estimate or bound for peak stress anywhere in the beam.
The assessment records actual values, signed margins and recovery instructions.
`PERFORMANCE_NOT_MET` retains those measurements while blocking publication
acceptance, downstream consumers and reuse. Increasing E or section size,
reducing force, or revising the explicit serviceability bound can be tested in
a fresh attempt; the adaptor never silently loosens a requirement.

`INVALID_BEAM` catches physical-domain problems before native launch.
`NUMERICAL_ACCEPTANCE_FAILED` distinguishes convergence/theory disagreement.
Malformed or altered evidence gives `VERIFICATION_FAILED`. Finite deadlines
cover every solver/version visit and verification; process-tree cancellation,
fresh directories and retained logs use the shared lifecycle. Runs are serial
inside each job, while independent jobs can use the workflow scheduler.
Common analytics, expressions and pointer edits replan complete independent
native states; there is no persistent solver or reverse editor synchronisation.

The baseline uses 0.4 m × 0.02 m × 0.02 m, E = 210 GPa, nu = 0.3 and F = -100 N. Material/load/mesh
variants and an unmet serviceability limit are provided. Newly tested corners
include Poisson 0/0.35, section aspect 0.5/2, slenderness 20/40 and the maximum mesh.
Those bounded fixtures are evidence, not proof across the continuous domain.

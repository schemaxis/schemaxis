# CalculiX rectangular elastic members

`schemaxis.calculix/1` assesses straight rectangular structural members from
physical intent: dimensions, isotropic elastic material, signed end resultants,
restraint and named measured requirements. The `cantileverBeam` operation supports
axial tension/compression, bending in both section directions, torsion, end bending
couples and their superposition. A clamped face accepts all six resultants; the
`axialSlide` restraint accepts pure axial loading while permitting Poisson
contraction. The original vertical-force documents remain valid.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/calculix-combined.json \
  --calculix /absolute/path/to/ccx --output-directory evidence/member
PYTHONPATH=src python3 tools/qualify_calculix.py \
  --executable /absolute/path/to/ccx --output-directory evidence/qualification
```

The target is stable **CalculiX 2.23**, still listed by the
[solver author](https://www.dhondt.de/) on 3 November 2026. The official
[2.23 manual](https://www.dhondt.de/ccx_2.23.htm.tar.bz2) defines C3D20R, `*CLOAD`,
`*BOUNDARY`, `*NODE PRINT` and `*EL PRINT`. The native `-v` response prints
`This is Version 2.23` and exits 201; only that exact response is accepted.
Host discovery, schema, planning and verification need no native Python modules.

## Physical intent and limits

The member spans positive x from 0 to `length_m`. Its solid rectangle is centred
at y=z=0; `width_m` is the full y dimension and `height_m` the full z dimension.
All lengths are m, forces N, stresses/modulus Pa, moments N m and rotations rad.
Every load component defaults to zero. At least one force or moment/length must
have magnitude at least 0.01 N.

| Field | Physical meaning and positive direction |
| --- | --- |
| `tipForceX_N` | Axial tension; negative means compression. |
| `tipForceY_N` | Force along +y, bending about z. |
| `tipForceZ_N` | Force along +z, bending about y. |
| `tipMomentX_Nm` | Right-hand torque about +x, rotating +y towards +z. |
| `tipMomentY_Nm` | Right-hand bending couple about +y; bends towards -z. |
| `tipMomentZ_Nm` | Right-hand bending couple about +z; bends towards +y. |

Moments act about the loaded face centre. Forces use uniform face traction;
bending couples use linear axial traction and torque uses linear transverse
traction. Exact degree-five face quadrature integrates the quadratic shape
functions and their first moments. Thus the assembled forces carry the declared
net force **and** moment. The quadratic corner weights can be negative; these are
consistent shape-function integrals, not separate reverse physical loads. No
rotational nodal constraints, arbitrary deck cards, executable expressions or
native commands are accepted.

`support: "clamped"` fixes all three translations on x=0. `axialSlide` fixes root
axial translations, y translations on the root y=0 symmetry line and z
translations on the root z=0 symmetry line. It removes rigid movement while
allowing uniform lateral contraction and accepts only nonzero axial force with
all five other resultants zero. It does not model a generic roller, pin or
simply-supported bending member.

| Property | Authored domain |
| --- | --- |
| Length | 0.001–10 m |
| Width and height | 0.00001–1 m |
| Length/max(width,height) | 20–40 |
| Width/height | 0.5–2 |
| Young's modulus | 1e6–1e12 Pa |
| Poisson ratio | 0–0.35 |
| Each force or moment component | -1e8–1e8 N or N m |
| Theory translation scale/length | at most 0.01 |
| Absolute-contribution normal strain scale | at most 0.001 |
| Conservative torsional shear strain scale | at most 0.001 |
| Absolute theory twist | at most 0.02 rad |
| Base axial cells | 12–24, default 12 |
| Base section cells per direction | 2–3, default 2 |
| Axial cell/minimum section cell | at most 10 |

The normal strain scale adds absolute axial and root bending contributions before
dividing by E; cancellation cannot hide a large load. Torsion uses the conservative
scale `abs(Mx)*max(width,height)/(J*G)`. Translation scales similarly add absolute
force/couple contributions per axis. Compression is a linear elastic response;
it does not establish stability against buckling. These bounds do not provide
yield, fatigue or material-failure certification.

## Independent numerical acceptance

Each run solves base `nx × n × n`, axial-refined `2nx × n × n` and fine
`2nx × 2n × 2n` C3D20R quadratic meshes. The largest fine mesh has 1728 elements
and 8869 nodes. A fourth independent native process reopens the **exact retained
fine deck bytes** and must reproduce its complete DAT output. Every stage must
have one converged linear static increment, exact tip/root node membership, eight
Gauss points per element, finite six-component stress and the intended integration
point coordinates within 1e-6 of each global dimension.

With area A=width×height, Iy=width×height³/12, Iz=height×width³/12 and
G=E/[2(1+nu)], the independent tip translation reference is:

```text
Ux = Fx*L/(E*A)
Uy = Fy*L^3/(3*E*Iz) + Mz*L^2/(2*E*Iz)
Uz = Fz*L^3/(3*E*Iy) - My*L^2/(2*E*Iy)
```

Measured translation is the end-face **area mean**, not maximum nodal translation
or mean displacement magnitude. Each active component must agree with theory
within 3% of the sum of its absolute force/couple contributions. Each independent
refinement changes every active translation and twist by at most 1% of that
component's theory scale. An unloaded component must remain below 1e-4 of the
largest translation or twist×section-size scale. Cancellation therefore remains
checked against the actual underlying load scale even when net theory displacement
is zero.

For full section sides a>=b, the independent rectangular Saint-Venant series is:

```text
J = a*b^3/3 * [1 - 192*b/(pi^5*a) * sum_odd(tanh(n*pi*a/(2*b))/n^5)]
theta_x = Mx*L/(G*J)
```

One hundred odd harmonics are retained. J for a unit square is approximately
0.140577015 m⁴. The observed twist is
`integral(y*Uz-z*Uy)dA/(Iy+Iz)` using exact integrated first moments of the
quadratic face functions. This removes mean translations and measures rigid
section rotation about x. Its fine value must agree within 3%. The torsional end
traction is an equilibrated linear distribution; the analytical reference is the
Saint-Venant interior response, away from clamp/end effects.

The independent Prandtl stress function for half-sides alpha>=beta is
`phi=(Mx/J)*[beta²-z²-(32*beta²/pi³)*sum_odd((-1)^((n-1)/2)*cosh(k*y)/cosh(k*alpha)*cos(k*z)/n³)]`,
where k=n*pi/(2*beta). Its derivatives give Sxy=dphi/dz and Sxz=-dphi/dy.
Stable exponential ratios avoid overflow. The opposite section orientation swaps
axes and reverses orientation. Native shear is projected onto even-y/odd-z parity
for Sxy and odd-y/even-z parity for Sxz; this isolates torsion from axial and
biaxial bending shear. Every interior projected Gauss stress must agree within 5%
of `abs(Mx)*max(width,height)/J`. This checks an independent stress field, rather
than inferring solver stress from applied torque or measured twist.

Interior Sxx is checked against
`Fx/A+(My-Fz*(L-x))*z/Iy-(Mz+Fy*(L-x))*y/Iz` at every Gauss point with x/L in
[0.3,0.7]. Error is at most 5% of the absolute-contribution analytical section
surface normal-stress scale. Pure torsion uses its nonzero torsional stress scale
for the expected zero normal stress. Dividing by a near-zero local neutral-axis
sample is avoided. Bending transverse shear is retained in output and von Mises
measurements, but is not claimed as a separately qualified local analytical field.

Root `RF` is actual support reaction because all external loads act on the other
face and no body loads exist. Summed native reactions must equal (-Fx,-Fy,-Fz).
Their moments about the root centre must equal (-Mx,L*Fz-My,-L*Fy-Mz). Residuals
are at most 1e-4 of the largest applied force-equivalent or moment-equivalent scale;
this accommodates printed-force precision. Separate active-response checks retain
sensitivity to small resultant components. These are explicit modelling and
numerical tolerances, not proof across every continuous input combination.

## Measurements, requirements and recovery

Stable artifact order is 0 `beam.inp` (editable text), 1 `interior-stress.csv`
(numeric table), 2 `beam-assessment.json` (text). The CSV contains IDs, x/y/z and
Sxx/Syy/Szz/Sxy/Sxz/Syz for native interior Gauss samples. The assessment contains
all stage measurements, signed requirement margins and recovery instructions.
Full DAT/FRD/STA and command logs remain in the attempt directory.

Requirements have unique lowercase names, a quantity and nonnegative `maximum`:

| Quantity | Measurement and units |
| --- | --- |
| `absTipAreaMeanUx_m`, `absTipAreaMeanUy_m`, `absTipAreaMeanUz_m` | Absolute area-mean component, m. |
| `tipAreaMeanTranslation_m` | Magnitude of the area-mean translation vector, m. |
| `absTipTwist_rad` | Absolute area-moment rotation about x, rad. |
| `maxInteriorSampleNormalStress_Pa` | Largest absolute sampled Sxx, Pa. |
| `maxInteriorSampleVonMises_Pa` | Largest equivalent stress computed from all six native sample components, Pa. |

Sampled stress is mesh-dependent and excludes clamp/loaded-end effects. Neither
stress quantity bounds surface/root/whole-member peaks or certifies failure.
`PERFORMANCE_NOT_MET` retains actual measurements and blocks acceptance,
downstream consumers and reuse. Change explicit dimensions, stiffness, load or
serviceability limits and run a fresh attempt; no limit changes itself.
`INVALID_BEAM` catches unsupported physical intent before native launch.
`NUMERICAL_ACCEPTANCE_FAILED` distinguishes theory/refinement disagreement;
`VERIFICATION_FAILED` covers altered or malformed evidence. Verification
reconstructs intent, decks, measurements, requirements and publication hashes, so
refreshing a digest cannot disguise changed geometry or loads.

Finite deadlines cover version and solver visits plus verification. Shared
process-tree cancellation, fresh directories and retained logs apply. Each job is
serial; independent jobs can use the workflow scheduler. Common analytics,
expressions and pointer edits create independent native states. There is no
persistent solver or reverse editor synchronisation.

Standalone examples include all six resultants, pure axial/clamped/sliding,
biaxial forces and couples, square/wide/tall torsion and force/couple cancellation.
Studio supplies complete combined, rectangular torsion, axial-contraction and
cancellation starters; field Help explains every component and measurement.
`calculix-to-calc.json` retains the existing numeric-table workflow handoff.

## Capability-family map

Completion of the supported member product is separate from whole-application
breadth. The following map is deliberately broader than the implemented workflow:

| CalculiX family | Status in Schemaxis |
| --- | --- |
| Geometry and meshing | Supported generated straight solid rectangles, quadratic structured bricks and automatic refinement. General geometry/imported mesh/deck unsupported. |
| Sections | One solid rectangular family, including square and nonsquare aspect0.5..2. Circular, hollow, shell and beam elements unsupported. |
| Materials | Supported homogeneous isotropic linear elasticity. Plasticity, hyperelasticity, anisotropy, damage and temperature dependence unsupported. |
| Loads | Supported six signed end force/couple resultants and superposition. Distributed body/surface/thermal/prestress loads and arbitrary loading locations unsupported. |
| Restraints | Supported fixed face and Poisson-contraction-permitting pure axial face. General constraints, joints, pinned/simply supported bending and assemblies unsupported. |
| Static structural | Supported small-strain/small-deformation linear axial/bending/torsional members. Nonlinear geometry, contact, buckling and general structural FEA unsupported. |
| Dynamics | Eigenmodes, harmonic, transient and explicit dynamics unsupported. |
| Other physics | Thermal, coupled thermomechanical, acoustics, electromagnetics and fluid analyses unsupported. CFD preparation/solver execution is outside the public-core boundary. |
| Results and design | Supported native displacement/twist, support equilibrium, complete interior stress components, sampled von Mises/normal requirements and reusable CSV. Peak-stress recovery, fatigue, optimisation and failure certification unsupported. |
| Lifecycle | Supported serial isolated native processes, bounded deadlines, cancellation, logs and exact saved-deck readback. MPI, interactive editing and native reverse sync unsupported. |

The [completion review](../verification/2026-11-03-calculix-six-resultants.md)
records new native evidence independently from retained historical receipts.

# GetDP layered conduction

GetDP solves a deliberately bounded engineering product: steady heat through a
layered wall and steady DC current through a layered resistor. Declare thickness,
conductivity, volumetric generation, end conditions and cross-sectional area;
Schemaxis generates the line finite element mesh and weak formulation, executes
GetDP, reopens its saved solution in a fresh process and independently checks the
actual node field and element flux. No Gmsh installation is required.

## Start and edit

Configure an absolute stable GetDP 3.5.0 executable using `schemaxis configure`,
or pass `--getdp /absolute/path/to/getdp`. Upstream's current stable version is
3.5.0; development snapshots are a separate, unqualified version family.

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/getdp-baseline.json
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/getdp-baseline.json --output-directory evidence/getdp-wall --getdp /absolute/path/to/getdp
PYTHONPATH=src python3 -m schemaxis verify evidence/getdp-wall
```

The standalone examples and Studio templates cover a uniform wall, composite
insulation, an internally heated slab, imposed flux with convection, and a DC
resistor. Edit the same layer/boundary JSON pointers through source, properties,
terminal patches or public agent drafts. Shared finite analytic visits support
explicit changed-material cases. Every effective input is planned and verified
separately; this does not establish an all-material-tolerance envelope.

## Inputs and units

`steadyHeat` uses temperature in kelvin, conductivity in W/(m K), source in W/m3,
flux in W/m2, convection coefficient in W/(m2 K), and ambient in kelvin.
`steadyCurrent` uses potential in V, conductivity in S/m, source in A/m3 and
current density in A/m2. Electrical generation means distributed current injection,
not Joule heating. There is no thermal/electrical coupling.

Layers are ordered from left x=0 to right. Each has a unique descriptive `name`,
positive `thickness_m`, positive `conductivity`, optional uniform `source` (zero
when omitted), and `cells` (16 when omitted). Cells are equal-length within each
layer and conform at perfectly contacting interfaces. Bounds are 1–16 layers,
2–128 cells per layer and 512 total. The conductivity/element-length stiffness
contrast must not exceed 1e8. Constant `area_m2` defaults to 1 and scales integrated
power/current, not the field or flux density.

Each end declares exactly one of:

- `{"kind":"value","value":300}` fixes temperature/potential.
- `{"kind":"flux","value":0}` fixes **outward** heat/current flux density.
  At the left, positive outward flux points toward negative x; at the right it
  points toward positive x. Negative flux injects heat/current.
- `{"kind":"convection","coefficient":100,"ambient":300}` removes heat at
  `coefficient * (temperature - ambient)`. Thermal only.

At least one value or thermal convection boundary anchors the field. Two flux
ends are refused, including compatible zero-net flux, because their absolute field
is undetermined. Thermal temperatures and ambients must be nonnegative kelvin;
the predicted nodal solution must also remain nonnegative.

Optional `limits` declares `minimumField`, `maximumField` and/or `maxAbsFlux`.
These compare mesh-node fields and element-midpoint fluxes. They do not certify
an unsampled interior continuum extremum, and coarsening is not a substitute for
choosing physically useful sample positions. An unmet limit produces
`PERFORMANCE_NOT_MET`, signed margins and retained failed-run evidence. It blocks
successful publication and downstream reuse.

## Physics and verification

Within each layer the PDE is `-(k u')' = s`, with axial flux `q = -k u'`.
The host verifier derives the exact piecewise-quadratic continuum solution using
`q(x+d) = q(x) + s*d` and
`u(x+d) = u(x) - q(x)*d/k - s*d*d/(2*k)`.
Two linear end equations determine the initial field and flux. For constant
source and conforming linear elements, native nodal values and element-midpoint
fluxes match this exact solution, including conductivity jumps.

Native `.pos` scalar/vector line records are parsed by coordinate and checked for
membership, continuity, finite values and absent transverse components. The
verifier source-corrects the first and last element-centre flux by half a cell's
source to recover physical boundary outflow, checks every internal interface and
checks total generation equals the sum of outward end flows. A fresh GetDP
process reloads retained `.pre`/`.res` files and exports the fields again. Offline
verification rebuilds the deterministic mesh/formulation and summaries, validates
publication/evidence hashes and compares published tables with native records;
exit status and success flags are never the physics criterion.

Tolerances are 2e-7 relative to max(1, exact field/flux) and 4e-7 for conservation,
covering GetDP ASCII precision while remaining far below useful input changes.
Table publication is checked at 1e-12. Reopened native fields agree at 1e-10
relative / 1e-9 absolute.

## Inspect and recover

`field.csv` contains x and temperature/potential. `flux.csv` contains element
centre x, signed positive-x heat/current density and one-based layer index.
`conduction-summary.json` retains SI units, extrema, source/outflow totals,
conservation residual, exact discrepancies, margins and explicit losses.
`model.pro` and `model.msh` are readable generated inputs. Native `.pre`, `.res`,
original/reopened fields and process logs are retained as verification evidence.

`INVALID_BOUNDARY` needs only the keys for the selected condition.
`UNANCHORED_FIELD` needs a value or thermal convection end.
`INVALID_LAYERS` needs unique layer names. `INVALID_TEMPERATURE` needs kelvin and
physically consistent source/end values. `ILL_CONDITIONED_FIELD` needs reduced
conductivity/element-size contrast. `RESOURCE_LIMIT` needs bounded cells/scales.
`PERFORMANCE_NOT_MET` needs review of actual signed margins and a fresh declared
input or justified requirement. `UNSUPPORTED_RUNTIME` requires stable 3.5.0.
Timeout and cancellation terminate owned native processes and preserve logs;
choose a new output directory for another attempt.

Run `PYTHONPATH=src python3 tools/qualify_getdp.py --output-directory evidence/getdp-check`
for native kit, adversarial evidence, public/terminal reuse, workflow resume and
finite-study checks. `--with-calc` additionally exercises the editable
`getdp-to-calc.json` field CSV handoff and requires an independently working Calc
runtime; that external consumer is qualified separately from GetDP.

## Capability-family map and boundaries

| Upstream family | Product decision | Implemented / verified |
| --- | --- | --- |
| Scalar thermal diffusion | Supported for constant-area layered steady walls | Fixed temperature, outward flux, convection, uniform per-layer source, composite materials, field/flux and global/interface conservation |
| Scalar electrical conduction | Supported for constant-area layered DC resistors | Fixed potential, outward current density, distributed injection, composite conductivities and total current |
| Material and boundary design variants | Supported as explicit inputs | Changed conductivity, source, boundary, area/cells and sampled-limit assessment; shared composition and finite visits |
| General 1D/2D/axisymmetric/3D meshing | Excluded | Generated conforming 1D line mesh only; no imported geometry/mesh |
| Nonlinear, time-dependent and harmonic models | Excluded | No radiation, transient, temperature-dependent properties, hysteresis or frequency domain |
| Electromagnetic forms, coupled multiphysics/circuits | Excluded | No magnetics, vector/edge/face elements, inductive/capacitive circuits or Joule coupling |
| Interactive ONELAB, arbitrary formulation authoring, MPI | Excluded | Deterministic generated model, isolated serial batch execution only |

This is a completed bounded product scope, not complete GetDP application
coverage. Numeric CSV is useful for downstream declared table consumers; CSV
alone loses topology, material/boundary intent and exact/conservation evidence,
so retain the summary and generated inputs. No implicit mesh conversion or
cross-adaptor geometry import is performed.

Public primary sources: [GetDP stable download and scope](https://getdp.info/),
[3.5.0 reference manual](https://getdp.info/doc/texinfo/getdp.html), including
Form0/BF_Node, FemEquation, Gauss integration, Resolution, PostProcessing,
Gmsh field output and `.pre`/`.res` format sections. Runtime GPL binaries remain
external; this adaptor generates its own domain-specific formulation.

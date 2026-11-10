# Elmer FEM solid thermal conduction

Elmer's `steadyHeat` evaluates the temperature and heat loss through a wall,
insulation stack or uniformly heated solid slab. Describe the materials and end
conditions in JSON; Schemaxis generates a bounded native mesh and SIF, runs
ElmerSolver in its own process, reloads its saved solution in a fresh process and
checks the results independently. Discovery, authoring and planning require only
Python's standard library. No Elmer Python module, GUI or Gmsh is required.

## Start and edit

Configure an absolute `ElmerSolver` executable using `schemaxis configure`, or
pass `--elmer` on execution. Target stable upstream release **26.2.1**. Its source
retains binary version **26.2**: the patch changes citation metadata, and runtime
reports cannot independently distinguish 26.2 from 26.2.1. Retain installation
source provenance separately. A binary reporting another major/minor is refused.

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/elmer-composite.json
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/elmer-composite.json \
  --output-directory evidence/my-wall --elmer /absolute/path/to/ElmerSolver
PYTHONPATH=src python3 tools/qualify_elmer.py \
  --output-directory evidence/my-elmer-qualification --elmer /absolute/path/to/ElmerSolver
```

Copy the baseline, composite insulation, volumetric heater, flux/convection or
two-film standalone example. Studio offers the same editable starters and typed
material/film snippets. Change conductivity, thickness or heating, replan and run
in a fresh directory. The optional shared workflow/composition layer uses the
same declared document and verification; no native handles cross operations.

## Physical document

`layers` are ordered from left (`x=0`) to right. Every layer requires a unique
`name`, positive `thickness_m` and positive `conductivity_W_mK` in W/(m K).
`heatGeneration_W_m3` defaults to zero; positive values add heat and negative
values remove it. `cells` defaults to 16 linear elements per layer. Interfaces
share nodes: temperature and physical heat flux are continuous, with perfect
thermal contact and no contact resistance. There are at most sixteen layers
and 512 total elements; conductivity/element-length stiffness contrast must not
exceed 1e8. `area_m2` defaults to one square metre and converts flux to total heat
rate; it does not alter a constant-area one-dimensional temperature solution.

Both `left` and `right` require exactly one end condition:

| kind | Required values | Meaning |
| --- | --- | --- |
| `value` | `value` in K | Prescribed surface temperature. |
| `flux` | `value` in W/m2 | Outward heat flux at that end; negative supplies heat. |
| `convection` | `coefficient` in W/(m2 K), `ambient` in K | Outward flux `h*(T-ambient)` with positive film coefficient. |

A temperature or convection end must anchor the field. Two flux ends leave an
arbitrary temperature offset even when their energy balance happens to match;
they are refused. All prescribed, ambient and exact continuum temperatures must
be nonnegative kelvin, including between-node extrema. Converting Celsius to
kelvin is the author's responsibility.

The equation is `-d/dx(k*dT/dx)=Q`. Element heat-flux tables use the +x Fourier
sign `q=-k*dT/dx`, whereas boundary inputs and summary outflows use outward sign.
A negative left outward flux is therefore positive +x heat input. For linear
finite elements, derived flux is constant within each element and equals the
exact quadratic solution's midpoint flux. Generation corrections recover physical
end and interface fluxes before conservation is assessed.

Optional `limits` contains `minimumField`/`maximumField` in K and `maxAbsFlux` in
W/m2. Omitted limits impose no design criterion; an empty object is allowed.
Minimum must not exceed maximum. Bounds apply literally to mesh-node temperature
and element-midpoint absolute flux, with signed margins retained in the summary.
They do not certify continuum extrema, continuous parameter envelopes or mesh
convergence. A real bound excess fails even inside physics comparison tolerances.

## Native mapping and independent verification

The trusted mapping writes Elmer mesh `202` line elements, `101` endpoint elements,
body/material/source records and `HeatSolve` / `HeatSolver`. Conductivity maps to
`Heat Conductivity`; density is one so `Heat Source` equals the authored volumetric
W/m3 source. `Temperature` maps fixed values. Elmer's natural `Heat Flux` load has
the opposite sign to the authored outward flux, so the mapping negates it.
Convection maps `Heat Transfer Coefficient` and `External Temperature`.
`Heat Flux BC=True` activates these natural conditions. Bandwidth optimisation is explicitly disabled so retained restart node/solver indices
remain identical. A direct UMFPACK linear
solve and a single constant-property steady iteration are used.

A separate `ResultOutputSolve` / `ResultOutputSolver` exports ASCII VTU.
The fresh-process reopen SIF declares `Temperature`, reads `thermal.result` and
sets `HeatSolver` to `Exec Solver=Never`; it cannot recompute a replacement
solution. Independent parsers check saved-result membership and values, VTU
coordinates/connectivity/material IDs and the reopened temperature export.
Elmer ASCII VTU uses eight significant digits; CSV and physics comparisons use
the full-precision native ASCII restart. The verifier checks the VTU values
against the documented eight-significant-digit rounding of those temperatures.

An independent closed-form piecewise-quadratic transfer calculation checks every
native node and derived element-midpoint flux. Source-corrected global and every
inter-element/interface heat balance are checked separately. It reconstructs the
effective plan from authored input, checks deterministic SIF/mesh, hashes every
publication and retained native evidence, and recomputes literal limit margins.
Process success, a file existing or a saved success flag alone cannot pass.
The transfer calculation is an independent check, never the source of published
native temperature values.

## Publications and recovery

`temperature.csv` holds x metres and nodal kelvin. `heat-flux.csv` holds midpoint
x, derived +x W/m2 and one-based layer index. `thermal-summary.json` retains units,
materials, extrema, exact-solution errors, generated/outflow watts, conservation
residual, sampled limits and losses. `model.sif`, `mesh/thermal.result` and
`mesh/native_t0001.vtu` are inspectable native publications. Keep the generated
mesh, `reopen.sif`, reopened VTU, authored/effective plans, version/solve/reopen
logs, owned process submissions/replay scripts and verification receipt together for independent verification.

`UNANCHORED_FIELD` needs a value or convection anchor. `INVALID_BOUNDARY` needs
only the fields for the selected kind. `INVALID_TEMPERATURE` needs a physically
valid kelvin range, including internal minima. `ILL_CONDITIONED_FIELD` needs
less stiffness contrast. `RESOURCE_LIMIT` needs fewer cells or bounded input
scales. `PERFORMANCE_NOT_MET` means verified native physics exceeded authored
sampled limits: inspect signed margins and revise the design or its criterion.
`INTERPRETER_NOT_FOUND` needs an absolute executable. `RUNTIME_UNAVAILABLE`
means the configured application could not identify itself (for example missing
shared libraries); inspect its version logs. `NATIVE_EXECUTION_FAILED` means the
solver or restart stage failed after identification; inspect the stage logs. `UNSUPPORTED_RUNTIME` needs
the declared stable runtime family. `VERIFICATION_FAILED` needs complete original
evidence or a fresh run, with logs retained. Existing output directories are
refused. Timeout/cancellation uses the shared owned process-tree runner and
retains an explicit incomplete/failed result; publication checks cancellation
and the total deadline again before success.

## Capability-family map and qualification scope

| Upstream family | Product scope | Implemented and checked | Exclusions / next gaps |
| --- | --- | --- | --- |
| Solid heat transfer | Layered insulation / heater sizing | Serial 1D constant-property HeatSolver; value, flux, film ends; generation, exact balances, sampled bounds | Radiation, transient, nonlinear properties, contact resistance and arbitrary geometry |
| Result/restart | Inspect and verify saved thermal solution | ASCII native restart, fresh-process no-solve VTU readback, full-precision CSV, explicit loss limits | General GUI editing/save or arbitrary deck interchange |
| General multiphysics | Potential later CAE workflows | No claims | Solid mechanics, eigenmodes, electromagnetics, acoustics and coupled thermal/electrical |
| Fluid flow | Separate private integration scope | Excluded | CFD execution and CFD-specific setup remain outside this public adaptor |
| Parallel/adaptive execution | Potential later qualification | No claims | MPI, adaptivity and general mesh convergence |

The eight canonical native cases cover a slab, changed conductivity, a two-material
wall, volumetric heater, flux/convection, two film ends, left flux/right temperature and left film/right flux. Literal expectations
come from Fourier series resistance, `QL²/(8k)` and film resistance. See the
[completion evidence](../verification/2026-11-04-elmer-completion.md). Qualification
is serial and source-bound; it does not establish every possible contrast or
Elmer application capability. A new source change can stale the receipt.

Public primary sources: [stable releases](https://github.com/ElmerCSC/elmerfem/releases),
[tagged implementation](https://github.com/ElmerCSC/elmerfem/tree/release-26.2.1),
[models manual](https://www.nic.funet.fi/pub/sci/physics/elmer/doc/ElmerModelsManual.pdf)
and [solver manual](https://www.nic.funet.fi/pub/sci/physics/elmer/doc/ElmerSolverManual.pdf).
See also the [generated operation reference](generated/elmer-operations.md).

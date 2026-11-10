# Cantera thermodynamic, equilibrium and reactor tables

`schemaxis.cantera/1` evaluates the **ideal-gas `ohmech` phase of `h2o2.yaml`** in
isolated Cantera 3.2.x Python processes. It publishes numeric state tables for
frozen-composition thermodynamics, TP/HP equilibrium and the time history of one
closed homogeneous reactor with optional fixed-bath heat exchange. The host remains free of Cantera, NumPy and
YAML dependencies. This is a hydrogen/oxygen mechanism with inert argon and
nitrogen; it cannot predict carbon chemistry, NOx, condensation, nonideal phases,
transport or flames. Its ignition delay is one declared criterion
applied to this model, not a measurement.

The authoritative [Cantera thermodynamic API](https://cantera.org/stable/python/thermo.html),
[NASA species models](https://cantera.org/stable/reference/thermo/species-thermo.html)
and [3.2.0 mechanism source](https://raw.githubusercontent.com/Cantera/cantera/v3.2.0/data/h2o2.yaml)
define the native data and calls. Public thermochemical coefficients are retained
unchanged in `thermochemistry.json`; source SHA256 and the upstream BSD licence
are retained alongside them. The native mechanism must match its qualified hash.
An upstream data change needs explicit requalification.

## Authoring and units

Start from [argon properties](../examples/schemaxis/cantera-minimal.json),
[TP equilibrium](../examples/schemaxis/cantera-equilibrium.json),
[adiabatic HP equilibrium](../examples/schemaxis/cantera-adiabatic.json) or a
[hydrogen/air ignition history](../examples/schemaxis/cantera-reactor.json).
Each input has two ordered nodes and an `output` selecting the second:

- `gas`: `pressure` in Pa, default 101325, range 1000–10000000; `basis` is `mole`
  (default) or `mass`. `composition` contains unique `{species, amount}` objects.
  Nonnegative amounts are normalised and must have a positive total. Species are
  H2, H, O, O2, OH, H2O, HO2, H2O2, AR and N2.
- `thermoSweep`: `inputs.input` references the gas. `temperatures` contains 2–100
  independent temperatures in K, range 300–3500. Composition stays frozen.
- `equilibrate`: the same temperature input, plus `mode` = `TP` (default) or `HP`.
  Each row starts from the declared composition, pressure and initial temperature.
  TP preserves temperature/pressure; HP preserves initial specific enthalpy and
  pressure while solving the final temperature. Final states outside 300–3500 K
  fail verification. Rows are not successive time steps.
- `reactorHistory`: integrates the gas in time; see
  [reactor time histories](#reactor-time-histories).

Configure an isolated Cantera interpreter or supply `--cantera /absolute/python`.
The runner uses the existing total timeout and owned-process cancellation. Use a
fresh output directory; failed/incomplete runs retain input, native logs and faults.
No arbitrary native scripts, external mechanisms or runtime reflection are authored.

## Reactor time histories

`reactorHistory` places the gas, at its own initial `temperature`, in one closed,
homogeneous reactor (adiabatic by default) and integrates the 29 h2o2 reactions in a Cantera
[`ReactorNet`](https://cantera.org/stable/python/zerodim.html#cantera.ReactorNet).
An optional fixed-temperature thermal bath exchanges heat through a linear wall. There are no inlets, surfaces or mixing.

- `model`: `constantPressure` (default) uses
  [`IdealGasConstPressureReactor`](https://cantera.org/stable/reference/reactors/ideal-gas-constant-pressure-reactor.html):
  pressure stays at the gas value, mass stays fixed and volume changes. Specific enthalpy is conserved only when adiabatic.
  `constantVolume` uses [`IdealGasReactor`](https://cantera.org/stable/reference/reactors/ideal-gas-reactor.html):
  the 1 m³ volume and density stay fixed, pressure rises and specific internal
  energy is conserved only when adiabatic.
- `temperature`: initial K, 300–3500, default 1000. Every sampled and integrator
  step must stay within 300–3500 K, otherwise the run fails with `UNSUPPORTED_STATE`.
- `times`: 2–100 strictly increasing sample times, each in seconds between 0
  and 1. Each becomes one CSV row; include 0 for the initial state. Repeated or
  decreasing times fail with `INVALID_TIMES`.
- `relativeTolerance` (1e-12–1e-8, default 1e-9), `absoluteTolerance`
  (1e-20–1e-12, default 1e-15) and `maxSteps` (100–100000 per sample interval,
  default 20000) are assigned to `ReactorNet.rtol`, `atol` and `max_steps` and read
  back. Looser tolerances are rejected: at 1e-6 the ignition delay moved by about
  0.9%, too close to the verification window to separate solver from model error.
- `ignitionTemperatureRise`: K, 10–1000, default 400. The **ignition delay** is the
  first time T reaches the initial T plus this rise, interpolated linearly in time
  between consecutive native integrator steps (a separate `step()` pass with the
  same settings, at most 200000 steps). It is `null` if not reached by the last
  sample. Other definitions, such as peak OH or peak dT/dt, can differ.

For stoichiometric hydrogen/air at 101325 Pa and constant pressure this mechanism
gives about 0.31 ms from 1000 K, 9 ms from 950 K and 0.24 s from 900 K; it does
not ignite within 1 s from 850 K. Place sample times around the expected rise; the
CSV does not interpolate between rows.

## Thermal exchange

Start from [hydrogen reactor with heat loss](../examples/schemaxis/cantera-thermal-reactor.json)
or the Studio **Hydrogen reactor with bath heat loss** template. Both reactor
models accept:

- `thermalConductance`: total conductance G in **W/K**, 0–1000000, default 0.
  Zero is adiabatic. Positive values use one fixed-area 1 m²
  [Cantera Wall](https://cantera.org/stable/python/zerodim.html#cantera.Wall)
  with `heat_transfer_coeff = G`, zero expansion coefficient and zero emissivity.
  Multiply a physical coefficient W/(m² K) by your physical area before entering
  G. It stays constant as a constant-pressure reactor changes volume.
- `bathTemperature`: absolute K, 300–3500, default 300; validated even when
  conductance is zero. The [Reservoir](https://cantera.org/stable/python/zerodim.html#cantera.Reservoir)
  remains at this temperature. There is no exchanged mass, finite bath heat
  capacity, wall heat capacity, radiation, moving piston or bath schedule.

Heat input to the gas is `G * (bathTemperature - T)` W. With constant closed
mass m, `dh/dt = G*(Tb-T)/m` at constant pressure and
`du/dt = G*(Tb-T)/m` at constant volume. The heat is divided by the **initial
mass**, never by a changing volume. Species still evolve through the same
29 reactions. Solver, temperature, time and resource bounds remain in force;
strong exchange can suppress ignition or require more integration steps.

The default example uses 1000 W/K to a 500 K bath. Increase conductance to
200000 W/K (and absoluteTolerance 1e-18 for the strong-cooling case) to cool the initial 1000 K mixture before ignition; compare zero
conductance for the adiabatic history. A hotter bath supplies energy instead.
The reported ignition delay is always the declared temperature-rise crossing:
**external heating can trigger it even for inert argon**. Check composition and
heat balance before interpreting the crossing as chemical ignition.

The host augments its independently integrated species/energy system with
`dQ_specific/dt = G*(Tb-T)/m`. Summary checks distinguish
`independentHeatInput_J_kg` from Cantera's instantaneous `nativeHeatRateOut_W`
(positive out of the reactor). The observed change of h or u must equal the
independent accumulated heat, within 1e-6 initial cp·T0 plus the NASA7
range-boundary jump. This 1 ppm budget covers numerical quadrature of the
additional heat state; it is separate from the stricter adiabatic conservation
budget. Native wall conductance/area/emissivity/expansion coefficient, each
sample's heat rate, the fixed reservoir temperature and zero expansion are read
back. Native energy change is not labelled adiabatic conservation.

For inert monatomic argon, cp and cv are constant and the exact solution is
`T(t) = Tb + (T0-Tb)*exp(-G*t/(m*c))`, with c=cp or cv according to the model.
Acceptance checks cooling and heating for both models against this independent
closed form, including the threshold-crossing time for heating.

## Publications and handoff

1. `results.csv`, kind `table`, has thirty numeric columns: initial/final K,
   pressure Pa, density kg/m³, enthalpy/internal energy J/kg, entropy/cp/cv J/(kg K),
   mean molecular weight kg/kmol, then ten `X_` mole and ten `Y_` mass fractions.
   Reactor tables replace the first column by `time_s` and report the sampled
   temperature and pressure.
2. `chemistry-summary.json`, kind `text`, records mechanism hash/phase, species,
   composition basis, normalised initial mole fractions, settings, temperature
   bounds, conservation/equilibrium residuals and explicit losses. Reactor
   summaries add the native reactor class, read-back solver settings and
   statistics, initial mass, the ignition criterion and delay, the independent
   delay and final equilibrium residual, and every verification tolerance.

Use shared table/text panels. Retain the summary when exporting the CSV; numbers
alone do not preserve mechanism assumptions. The editable
[Cantera → Calc workflow](../examples/schemaxis/cantera-to-calc.json) imports the
CSV into a verified workbook. Calc's generic statistics apply to numeric columns;
its column sums do not imply a physical conservation law.

Source and property authoring use the common durable draft and revision checks.
Change pressure, composition or the temperature list, plan a fresh revision,
execute, inspect and verify. Unchanged inline inputs and verified artifacts can
be reused on workflow resume. There is no application-specific GUI or live worker.

## Independent verification

The host evaluates NASA7 heat capacities, enthalpies and entropies directly from
public coefficients, then ideal-mixture density, internal energy and mixing entropy.
It checks every published property and mass/mole fraction, normalisation, elemental
moles per kg, pressure and the operation's T or enthalpy constraint. Equilibrium
additionally requires each accessible species chemical potential to equal the sum
of its elemental potentials, within 2e-5 RT. Absent elements cannot appear. This
checks the ideal-mixture equilibrium equations independently of Cantera's solver.

A second Cantera process reloads the saved CSV states and checks their properties.
Published and native evidence digests, exact mechanism bytes and authored/effective
plan agreement are rechecked offline. No native installation is needed to verify
an existing run. Acceptance includes analytic argon properties and closed-form
H2 dissociation, plus reactive TP and HP cases and corruption/lifecycle probes.
These qualify the stated mechanism and numerical constraints, not an experimental
model or a safety calculation.

Reactor histories are checked against an independent host model rather than
against Cantera itself. The 29 public rate expressions in `kinetics.json`
(elementary, three-body, Troe falloff; reverse rates from NASA7 equilibrium
constants) and the closed-reactor equations including the declared fixed-bath heat exchange are evaluated in plain
Python and integrated with a four-stage L-stable Rosenbrock method. The verifier
requires:

- native and fresh-process net production rates at every sample equal the
  independent rates within 1e-10 of the gross forward-plus-reverse rate;
- each sampled T and mole fraction lies within the independent solution over a
  ±1% time window (plus 0.5 K and 1e-6), so steep ignition fronts are compared by
  timing rather than by an unstable pointwise value;
- the native ignition delay agrees with the independent delay within 1%;
- element inventories (1e-9 relative), reactor mass, density for constant volume,
  are conserved; when adiabatic, specific enthalpy or internal energy is conserved. The adiabatic energy tolerance is
  1e-7 cp·T0 plus the 0.19 J/kg NASA7 range-boundary jump when samples cross 1000 K;
- the read-back reactor class, tolerances, step limit, energy/chemistry flags and
  the 1 m³ initial volume match the plan, and the initial mass equals the
  independent initial density.

The summary reports the final chemical-potential residual; long histories should
approach it to zero (HP or UV equilibrium). Acceptance also includes an inert argon
reactor whose state must not change. The independent model checks the native
integration of the stated mechanism, not the mechanism against experiments.

`INVALID_COMPOSITION` needs distinct supported species and a positive total.
`INVALID_TIMES` needs strictly increasing reactor sample times. `UNSUPPORTED_STATE`
means a reactor temperature left 300–3500 K; dilute the mixture or start colder.
`INTERPRETER_NOT_FOUND` means the configured path is not an executable absolute
Python. Native faults keep three states distinct, each with recovery text, and
none leaves a published table: `NATIVE_UNAVAILABLE` means that Python cannot
import Cantera; `UNSUPPORTED_RUNTIME` means Cantera is present but is not 3.2.x
(`observed.version` names it); `NATIVE_EXECUTION_FAILED` retains the native
diagnostic, including a mismatched mechanism or nonconvergent state, in
`native-fault.json`, `build.stderr` and `build.stdout`. A worker fault record that
is malformed or names another code is reported as `NATIVE_EXECUTION_FAILED`.
Verifying an existing run never needs a runtime, but a receipt from a Cantera that
is not 3.2.x fails `VERIFICATION_FAILED`.
`VERIFICATION_FAILED` can indicate an out-of-range HP state or numerical/provenance
failure; repair the input or investigate it rather than relaxing tolerances.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/cantera-equilibrium.json \
  --cantera /absolute/python --output-directory new-equilibrium
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/cantera-reactor.json \
  --cantera /absolute/python --output-directory new-ignition
PYTHONPATH=src python3 tools/qualify_cantera.py \
  --config /path/to/private-config.json --output-directory new-acceptance
```

## Capability-family map

| Upstream family | Product scope and verified status | Remaining exclusions |
| --- | --- | --- |
| Thermodynamics | Frozen ideal-gas ten-species h2o2 property tables; NASA7 independent checks | Other mechanisms, nonideal/condensed phases, external species |
| Equilibrium | TP and HP sweeps; independent chemical-potential/element/energy checks | Other constraints and multiphase equilibrium |
| Homogeneous kinetics | Closed constant-pressure and constant-volume histories; 29 public rates, independent Rosenbrock trajectory/criterion | Open networks, flow devices, surfaces and custom mechanisms |
| Reactor thermal coupling | Fixed-temperature bath, total constant conductance, both models; native Wall readback, independent heat balance, analytic inert heating/cooling | Radiation, moving walls, wall heat capacity, finite or scheduled baths, multiple reactors |
| Transport and reacting flow | Not exposed | Transport coefficients, spatial flow, flames and flame speed |
| Mechanism management | Pinned upstream h2o2 bytes and public coefficient/rate records | Import, conversion, editing and runtime reflection |

This completes the declared fixed-bath closed-reactor workflow. It does not claim
coverage of general Cantera reactor networks or the whole upstream application.

```sh
PYTHONPATH=src python3 tools/qualify_cantera_thermal.py \
  --cantera /absolute/python --output-directory new-thermal-acceptance
```

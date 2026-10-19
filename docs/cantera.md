# Cantera thermodynamic, equilibrium and reactor tables

`schemaxis.cantera/1` evaluates the **ideal-gas `ohmech` phase of `h2o2.yaml`** in
isolated Cantera 3.2.x Python processes. It publishes numeric state tables for
frozen-composition thermodynamics, TP/HP equilibrium and the time history of one
closed adiabatic homogeneous reactor. The host remains free of Cantera, NumPy and
YAML dependencies. This is a hydrogen/oxygen mechanism with inert argon and
nitrogen; it cannot predict carbon chemistry, NOx, condensation, nonideal phases,
transport, flames or heat loss. Its ignition delay is one declared criterion
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
adiabatic, homogeneous reactor and integrates the 29 h2o2 reactions in a Cantera
[`ReactorNet`](https://cantera.org/stable/python/zerodim.html#cantera.ReactorNet).
There are no walls, heat loss, inlets, surfaces or mixing.

- `model`: `constantPressure` (default) uses
  [`IdealGasConstPressureReactor`](https://cantera.org/stable/reference/reactors/ideal-gas-constant-pressure-reactor.html):
  pressure stays at the gas value and specific enthalpy is conserved.
  `constantVolume` uses [`IdealGasReactor`](https://cantera.org/stable/reference/reactors/ideal-gas-reactor.html):
  the 1 m³ volume and density stay fixed, pressure rises and specific internal
  energy is conserved.
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
constants) and the adiabatic closed-reactor equations are evaluated in plain
Python and integrated with a four-stage L-stable Rosenbrock method. The verifier
requires:

- native and fresh-process net production rates at every sample equal the
  independent rates within 1e-10 of the gross forward-plus-reverse rate;
- each sampled T and mole fraction lies within the independent solution over a
  ±1% time window (plus 0.5 K and 1e-6), so steep ignition fronts are compared by
  timing rather than by an unstable pointwise value;
- the native ignition delay agrees with the independent delay within 1%;
- element inventories (1e-9 relative), reactor mass, density for constant volume,
  and specific enthalpy or internal energy are conserved; the energy tolerance is
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
`INTERPRETER_NOT_FOUND` needs the isolated runtime. `NATIVE_EXECUTION_FAILED` retains
the native diagnostic, including a mismatched mechanism or nonconvergent state.
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

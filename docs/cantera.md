# Cantera thermodynamic and equilibrium tables

`schemaxis.cantera/1` evaluates the **ideal-gas `ohmech` phase of `h2o2.yaml`** in
isolated Cantera 3.2.x Python processes. It publishes numeric state tables for
frozen-composition thermodynamics and TP/HP equilibrium. The host remains free of
Cantera, NumPy and YAML dependencies. This is a hydrogen/oxygen mechanism with
inert argon and nitrogen; it cannot predict carbon chemistry, NOx, condensation,
nonideal phases, transport or ignition delays.

The authoritative [Cantera thermodynamic API](https://cantera.org/stable/python/thermo.html),
[NASA species models](https://cantera.org/stable/reference/thermo/species-thermo.html)
and [3.2.0 mechanism source](https://raw.githubusercontent.com/Cantera/cantera/v3.2.0/data/h2o2.yaml)
define the native data and calls. Public thermochemical coefficients are retained
unchanged in `thermochemistry.json`; source SHA256 and the upstream BSD licence
are retained alongside them. The native mechanism must match its qualified hash.
An upstream data change needs explicit requalification.

## Authoring and units

Start from [argon properties](../examples/schemaxis/cantera-minimal.json),
[TP equilibrium](../examples/schemaxis/cantera-equilibrium.json) or
[adiabatic HP equilibrium](../examples/schemaxis/cantera-adiabatic.json).
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

Configure an isolated Cantera interpreter or supply `--cantera /absolute/python`.
The runner uses the existing total timeout and owned-process cancellation. Use a
fresh output directory; failed/incomplete runs retain input, native logs and faults.
No arbitrary native scripts, external mechanisms or runtime reflection are authored.

## Publications and handoff

1. `results.csv`, kind `table`, has thirty numeric columns: initial/final K,
   pressure Pa, density kg/m³, enthalpy/internal energy J/kg, entropy/cp/cv J/(kg K),
   mean molecular weight kg/kmol, then ten `X_` mole and ten `Y_` mass fractions.
2. `chemistry-summary.json`, kind `text`, records mechanism hash/phase, species,
   composition basis, normalised initial mole fractions, settings, temperature
   bounds, conservation/equilibrium residuals and explicit losses.

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

`INVALID_COMPOSITION` needs distinct supported species and a positive total.
`INTERPRETER_NOT_FOUND` needs the isolated runtime. `NATIVE_EXECUTION_FAILED` retains
the native diagnostic, including a mismatched mechanism or nonconvergent state.
`VERIFICATION_FAILED` can indicate an out-of-range HP state or numerical/provenance
failure; repair the input or investigate it rather than relaxing tolerances.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/cantera-equilibrium.json \
  --cantera /absolute/python --output-directory new-equilibrium
PYTHONPATH=src python3 tools/qualify_cantera.py \
  --config /path/to/private-config.json --output-directory new-acceptance
```

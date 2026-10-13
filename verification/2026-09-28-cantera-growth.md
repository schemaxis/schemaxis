# Cantera thermochemistry through the adaptor kit

A reviewed node scaffold now delivers `gas`, `thermoSweep` and `equilibrate` in
`schemaxis.cantera/1`. Discovery/planning remains dependency-free; native Cantera
runs in separate build/reopen processes. No framework routing changes were needed.
The [guide](../docs/cantera.md) and [delivery bundle](../src/schemaxis/adaptors/cantera/readiness.json)
state units, mechanisms, losses, limits, interpretation and recovery.

The official [stable API](https://cantera.org/stable/python/thermo.html) identifies
3.2.0. That version was installed in an isolated ignored environment and exercised.
The [public h2o2.yaml source](https://raw.githubusercontent.com/Cantera/cantera/v3.2.0/data/h2o2.yaml)
was independently fetched and matched byte-for-byte to the native mechanism
(SHA256 `0efc6c52862741a29e0c29b65d979c7d8cb409db5282bca83b9c5437b3d8c8d4`).
Public NASA7 coefficients and the upstream BSD licence are retained in the adaptor.
Only ideal-gas `ohmech` is exposed; N2/Ar are inert and no NOx/carbon, multiphase,
kinetic, transport or ignition-delay support is claimed.

## Fresh native and reuse evidence

Six native kit cases pass on Cantera 3.2.0:

- Argon cp = 5R/(2M), cv = 3R/(2M), ideal density and analytic enthalpy.
- Doubled pressure gives doubled density and unchanged heat capacity.
- Hydrogen/oxygen/nitrogen TP equilibrium at 1000, 1500 and 2000 K.
- Hydrogen/air HP equilibrium from 300, 400 and 500 K: observed final temperatures
  2387.636900, 2438.112772 and 2485.955872 K. These are observations, not copied
  acceptance expectations; independent energy/conservation/equilibrium equations
  verify every row.
- Pure-H2 dissociation checked against a separate closed-form extent calculation
  using the public NASA7 equilibrium constant.
- Mass-basis equimolar H2/O2 at 300, 1000 and 3500 K, including the NASA7 range
  boundary and both supported temperature limits.

The host independently recomputes density, cp/cv, enthalpy, internal energy,
entropy, mean molecular weight, fraction conversion and elemental moles/kg.
Equilibrium checks chemical potentials for every accessible species within
2e-5 RT. TP holds T/P; HP holds enthalpy/P. A fresh native process reloads CSV
states. All **60 missing/tampered evidence probes** and both lifecycle checks pass.
A separately modified mechanism remains rejected even after refreshing its
manifest digest; offline verification pins actual bytes to the qualified mechanism.

Cantera → Calc passes for two pressures, all thirty numeric columns and three
rows. Workbook readback matches, and every job is reused on unchanged resume.
The public bounded-context/source/property/plan/execute/inspect loop exercises all
six cases and rejects zero composition. A terminal-console edit reopens the same
durable draft, rejects the previous plan as stale and doubles verified argon
density from **1.622848417231445 to 3.24569683446289 kg/m³**. This is deterministic
client/console procedure evidence, not an autonomous-model evaluation.

## Reproduction

```sh
PYTHONPATH=src python3 tools/qualify_cantera.py \
  --config /path/to/private-config.json --output-directory new-acceptance
PYTHONPATH=src python3 -m schemaxis adaptor record new-acceptance/native/qualification.json
PYTHONPATH=src python3 -m schemaxis readiness --admission --check
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --output-directory new-host
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
```

Bulk native evidence is in `evidence/cantera-final-acceptance/`; the initial run
is retained separately. Nine focused host tests cover the delivery contract,
composition, bounds, analytic properties, all thirty columns, false native success
and rejection of nonequilibrium reactants. User configuration and PATH are unchanged;
acceptance uses its own ignored configuration and isolated runtime.

Full regression: **748 passed, 22 skipped (770 total)** in 207.434 seconds.
Both progressive capability protocol tests pass (65.311 seconds). All **53**
generated references are current. Catalogue-wide host conformance and development
admission pass for twelve adaptors / fourteen routes. Thirteen registered native
receipts are source-current, covering 34 cases, 352 integrity probes and 26
lifecycle probes across the catalogue; only Gmsh and Cantera were freshly run for
this extension. The Cantera release monitor reports 3.2.0 current.

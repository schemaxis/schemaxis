# Cantera fixed-bath closed-reactor completion — 4 November 2026

Scope: extend `schemaxis.cantera/1` `reactorHistory` with total
`thermalConductance` (W/K) and `bathTemperature` (K), preserving zero-conductance
adiabatic defaults. Both closed constant-pressure and constant-volume models
are included. This review covers the extension and regressions; the capability
map in `docs/cantera.md` retains explicit upstream exclusions.

## API and model basis

Latest stable release checked 4 November 2026 against the public
[GitHub latest release API](https://api.github.com/repos/Cantera/cantera/releases/latest):
`v3.2.0`, not a prerelease, published 18 November 2025. The official
[Wall API](https://cantera.org/stable/python/zerodim.html#cantera.Wall) and
[reactor interaction equations](https://cantera.org/stable/reference/reactors/interactions.html#walls)
define linear heat flow and the fixed-temperature Reservoir. The accepted
runtime remains Cantera 3.2.x with the unchanged pinned h2o2 mechanism hash.
Native acceptance was newly executed with Cantera 3.2.0 on Python 3.14. No
native imports occur during discovery or planning.

The vessel starts at 1 m³. Its initial mass stays fixed in both models;
constant pressure changes volume. Heat input is G(Tbath−T), divided by the
fixed initial mass in the independent energy equation. G is the total W/K,
not per instantaneous volume or area. Native Wall area is fixed at 1 m²,
heat-transfer coefficient is G, expansion coefficient and emissivity are zero.
The Reservoir temperature is fixed; no mass is exchanged. Wall/bath heat
capacity, radiation, moving walls, schedules, open/multiple reactors, surfaces,
external mechanisms and reacting flow are excluded.

A host Rosenbrock state additionally integrates accumulated heat J/kg. Native
h/u change is checked against this independent integral; native instantaneous
outward heat rate W is separately read back. The thermal balance tolerance is
1e-6 initial cp·T0 plus the public NASA7 boundary jump, allowing accumulated
quadrature error. Adiabatic conservation retains 1e-7 cp·T0 plus the jump.
Native/host trajectories, species production, sample timing, element/mass
inventories and the declared temperature-rise criterion retain their existing
independent checks. Hot-bath heating can cross this criterion even for inert
gas; guidance and summary explicitly say this does not prove chemical ignition.

## Completion checklist

| Item | Retained review and checks |
| --- | --- |
| registration | Existing node/workflow route, process-only execution and unsupported features preserved; bounded thermal scope declared in manifest/readiness/capabilities. |
| schema | Two finite numeric fields with explicit defaults and bounds; generated literal/authored reference parity checked. |
| semantics | Host validates W/K 0–1000000 and bath 300–3500 K before native assignment, including wrong types, NaN, infinities and negatives at exact field locations. Fixed mass and total conductance semantics are documented. |
| native-mapping | Native Wall/Reservoir public APIs, coefficient/area/bath/emissivity/expansion readback and each sample heat/expansion rate checked against the effective plan; cloned gas avoids state aliasing. |
| execution | Isolated native build plus separate CSV reopening process; offline evidence digests, plan identity, independently integrated energy/kinetics and forged heat-flow rejection. Tiny deadline fails without publication. Shared workflow resume reuses verified unchanged thermal input. |
| discovery | Reviewed heat-loss, thermal-bath and Newton-cooling search cases; existing neighbouring equilibrium and negative flame-speed/methane cases retained. |
| guidance | Both fields explain physical meaning, SI units, defaults, valid bounds, area/volume mistakes, constant-pressure mass/volume and inert bath-heating interpretation. Existing operation/model explanations updated. |
| help | Local thermal section, primary Wall/Reservoir references and contextual packaged Help generated and audited. Recovery explains tightening absoluteTolerance for trace negative native fractions without relaxing verification. |
| examples | Standalone reactive thermal example, editable Studio template, schema-invalid negative conductance example, analytic inert heating/cooling conformance cases for both models and independently integrated reactive cases. |
| tests | Targeted Cantera host/falsification tests, guidance/reference/Studio/search, host and native conformance, assessment freshness and generated-index parity recorded below. |
| qualification | Local availability, host checks and newly executed source-bound native receipt are separate. Final integration changes require refreshing source-bound qualification. |
| maintenance | Stable 3.2.0 confirmed from primary upstream; mechanism data unchanged. Thermal acceptance recipe and reviewed scope/limitations in upstream/readiness/assessment records. Scores retained as subjective estimates, not increased for this extension. |

## Newly executed evidence

All computational jobs ran inside the private bounded resource envelope with
no PATH changes. Local bulk receipts remain under `evidence/` and are not shipped.
Final command results and native values are recorded after acceptance below.

A deliberately strong 200000 W/K constant-volume cooling case at default
absoluteTolerance 1e-15 produced a −2.45e-16 radical fraction. Strict existing
nonnegative-fraction verification correctly rejected it. The stress case uses
authored 1e-18 absolute tolerance; no output clipping or verifier relaxation was
introduced. Failed attempts remain distinct from the accepted receipts.

Final focused results:

- `python3 -m unittest discover -s tests/unit -p 'test_cantera*.py' -q`:
  40 passed; the subsequently added thermal Studio field-projection test was
  checked in the final six-test thermal module run.
- `studio_guidance.py --app cantera --check`: 40 reviewed, 13 reference-derived,
  zero pending/stale. `schemaxis reference --check`: 166 current files.
  Packaged Help check: 1473 current topics. Production Studio search: 516 passed.
- Assessment real-output parity/host module: 20 passed; generated current index
  check passed. Scores remain 10% breadth and 75% abstraction with reviewed
  workflow scopes and explicit limitations.
- Host conformance passed, including typed defaults and invalid thermal fields.
  Admission: 73 passes, zero failures, zero required unknowns. These are
  structural host results, not native availability or scientific endorsement.
- Canonical native conformance: all 16 named cases passed, including the ten
  retained legacy thermo/equilibrium/adiabatic cases and six thermal cases.
  Native timeout and pre-launch cancellation passed. Local bulk receipt:
  `evidence/cae5-cantera-conformance/qualification.json`. Subsequent strict numeric
  wall readback guards were tested by the final host falsification module and
  the final dedicated native thermal acceptance below.
- Final `tools/qualify_cantera_thermal.py`: ten physical runs passed, plus
  forged-digest heat-flow rejection, invalid-before-launch rejection, deadline
  without publication, verified workflow resume and two same-draft public
  authoring executions at changed conductance.
  Bulk report: `evidence/cae5-cantera-thermal-final/report.json`.

| Native case | Constant pressure | Constant volume |
| --- | --- | --- |
| Argon, 1000→500 K bath, 1000 W/K, T(1 s) | 509.649591 K | 500.694283 K |
| Argon, 1000→1500 K bath, 1000 W/K, T(1 s) | 1490.350405 K | 1499.305712 K |
| Inert hot-bath +400 K crossing | 0.407756515 s | 0.244681929 s |
| Reactive adiabatic T(20 ms) | 2692.813327 K | 2908.623542 K |
| Reactive 500 K bath, 1000 W/K, T(20 ms) | 2651.064063 K | 2860.151732 K |
| Reactive 500 K bath, 200000 W/K, T(20 ms) | 500.008736 K | 500.000127 K |

Argon temperatures match independent closed forms within 2e-5 K; heating
crossings match analytic times within 0.1%. Reactive 1000 W/K delays increase
from 0.311137 to 0.312313 ms (pressure) and 0.304137 to 0.305654 ms (volume).
The strong-cooling cases never cross the +400 K criterion. Maximum energy
residual across the ten final runs was 0.139729 J/kg, dominated by the retained
NASA7 boundary discontinuity; the largest purely inert balance residual was
0.008904 J/kg. Samples near ignition retain independent kinetics/energy checks.

A worker full-host-suite attempt was explicitly interrupted on coordination
request to avoid duplicate broad jobs; its partial transcript is retained and
is not counted as a passing suite. Root integration owns the combined full-host
suite, shared generated assets and final source-bound native registration.
Temporary generated material was checked locally and restored before handoff;
conservative qualification digests therefore require final regeneration and
native requalification in the integrated tree. The unchanged package receipt
is visibly stale until that final integration check, rather than relabelled.
